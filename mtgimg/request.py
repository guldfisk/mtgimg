import typing as t

from abc import ABC, abstractmethod
import os

from PIL import Image
from promise import Promise
from lazy_property import LazyProperty
from functools import lru_cache

from mtgorp.models.persistent.printing import Printing
from mtgimg import paths


class Imageable(ABC):

	@abstractmethod
	def get_image(
		self,
		size: t.Tuple[int, int],
		loader: 'ImageLoader',
		back: bool = False,
		crop: bool = False
	) -> Image.Image:
		pass

	@abstractmethod
	def get_image_name(self, back: bool = False, crop: bool = False) -> str:
		pass

	@abstractmethod
	def get_image_dir_name(self) -> str:
		pass

	@abstractmethod
	def has_back(self) -> bool:
		pass


picturable = t.Union[Imageable, Printing]


class ImageRequest(object):

	def __init__(self, pictured: picturable, back: bool = False, crop: bool = False):
		self._pictured = pictured
		self._back = back
		self._crop = crop

	@LazyProperty
	def has_image(self) -> bool:
		if self._back:
			if isinstance(self._pictured, Imageable):
				return self._pictured.has_back()
			return bool(self._pictured.cardboard.back_cards)

		if isinstance(self._pictured, Imageable):
			return True
		return bool(self._pictured.cardboard.front_cards)

	def _name_no_extension(self) -> str:
		if self._back:
			if self.has_image:
				return str(self._pictured.id) + 'b'
			return 'cardback'
		return str(self._pictured.id)

	@property
	def name(self) -> str:
		return (
			self._pictured.get_image_name()
			if isinstance(self._pictured, Imageable) else
			self._name_no_extension() + ('_crop' if self._crop else '')
		)

	@property
	def extension(self) -> str:
		return 'png'

	@LazyProperty
	def dir_path(self) -> str:
		if self.has_image:
			if isinstance(self._pictured, Imageable):
				return os.path.join(
					paths.IMAGES_PATH,
					self._pictured.get_image_dir_name(),
				)
			return os.path.join(
				paths.IMAGES_PATH,
				self._pictured.expansion.code,
			)
		return paths.CARD_BACK_DIRECTORY_PATH

	@LazyProperty
	def path(self) -> str:
		return os.path.join(
			self.dir_path,
			self.name + '.' + self.extension,
		)

	@LazyProperty
	def remote_card_uri(self) -> str:
		return 'https://api.scryfall.com/cards/multiverse/{}'.format(self.pictured.id)

	@property
	def pictured(self) -> picturable:
		return self._pictured

	@property
	def back(self) -> bool:
		return self._back

	@property
	def crop(self) -> bool:
		return self._crop

	def cropped_as(self, crop: bool) -> 'ImageRequest':
		return self.__class__(self._pictured, self._back, crop)

	def __hash__(self) -> int:
		return hash(
			(
				self._pictured,
				self._back,
				self._crop,
			)
		)

	def __eq__(self, other) -> bool:
		return (
			isinstance(other, self.__class__)
			and self._pictured == other._pictured
			and self._back == other._back
			and self._crop == other._crop
		)

	def __repr__(self) -> str:
		return '{}({}, {}, {})'.format(
			self.__class__.__name__,
			self._pictured,
			self._back,
			self._crop,
		)


class ImageLoader(ABC):

	@abstractmethod
	def get_image(
		self,
		pictured: picturable = None,
		back: bool = False,
		crop: bool = False,
		image_request: ImageRequest = None,
	) -> Promise:
		pass

	def get_default_image(self) -> Promise:
		pass

	@classmethod
	@lru_cache(maxsize=128)
	def open_image(cls, path) -> Image.Image:
		return Image.open(path)