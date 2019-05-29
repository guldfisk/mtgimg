import typing as t

from threading import Lock
from abc import ABC, abstractmethod
import os

from PIL import Image
from promise import Promise
from lazy_property import LazyProperty
from functools import lru_cache

from mtgorp.models.persistent.printing import Printing
from mtgimg import paths


class ImageFetchException(Exception):
	pass


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

	@classmethod
	@abstractmethod
	def get_image_dir_name(cls) -> str:
		pass

	@abstractmethod
	def has_back(self) -> bool:
		pass

	@abstractmethod
	def __hash__(self) -> int:
		pass


pictureable = t.Union[Imageable, Printing]


class ImageRequest(object):

	def __init__(
		self,
		pictured: t.Optional[pictureable] = None,
		*,
		pictured_type: t.Union[t.Type[Printing], t.Type[Imageable]] = Printing,
		picture_name: t.Optional[str]= None,
		back: bool = False,
		crop: bool = False,
		save: bool = True,
	):
		self._pictured = pictured
		self._pictured_type = pictured_type
		self._pictured_name = picture_name if isinstance(picture_name, (str, type(None))) else str(picture_name)
		self._back = back
		self._crop = crop
		self._save = save

	@LazyProperty
	def has_image(self) -> bool:
		if self._pictured_name is not None:
			return True

		if self._back:
			if isinstance(self._pictured, Imageable):
				return self._pictured.has_back()
			return bool(self._pictured.cardboard.back_cards)

		if isinstance(self._pictured, Imageable):
			return True
		return bool(self._pictured.cardboard.front_cards)

	def _name_no_extension(self) -> str:
		if self._pictured_name is not None:
			print(self._pictured_name)
			return self._pictured_name

		if self._back:

			if self.has_image:
				return (
					self._pictured.get_image_name()
					if isinstance(self._pictured, Imageable) else
					str(self._pictured.id)
				) + '_b'

			return 'cardback'

		return (
			self._pictured.get_image_name()
			if isinstance(self._pictured, Imageable) else
			str(self._pictured.id)
		)

	@property
	def name(self) -> str:
		return (
			self._name_no_extension()
			+ ('_crop' if self._crop else '')
		)

	@property
	def extension(self) -> str:
		return 'png'

	@classmethod
	def _get_imageable_dir_path(cls, imageable: t.Union[Imageable, t.Type[Imageable]]) -> str:
		return os.path.join(
			paths.IMAGES_PATH,
			'_' + imageable.get_image_dir_name(),
		)

	@LazyProperty
	def dir_path(self) -> str:
		if self._pictured_name is not None:
			if issubclass(self._pictured_type, Imageable):
				return self._get_imageable_dir_path(
					self._pictured_type
				)
			return paths.IMAGES_PATH

		if self.has_image:
			if isinstance(self._pictured, Imageable):
				return self._get_imageable_dir_path(
					self._pictured
				)
			return paths.IMAGES_PATH

		return paths.CARD_BACK_DIRECTORY_PATH

	@LazyProperty
	def path(self) -> str:
		return os.path.join(
			self.dir_path,
			self.name + '.' + self.extension,
		)

	@LazyProperty
	def remote_card_uri(self) -> str:
		return f'https://api.scryfall.com/cards/multiverse/{self.pictured.id}'

	@property
	def pictured(self) -> pictureable:
		return self._pictured

	@property
	def back(self) -> bool:
		return self._back

	@property
	def crop(self) -> bool:
		return self._crop

	@property
	def save(self) -> bool:
		return self._save

	@property
	def pictured_name(self) -> t.Optional[str]:
		return self._pictured_name

	@property
	def pictured_type(self) -> t.Union[t.Type[Printing], t.Type[Imageable]]:
		return self._pictured_type

	def cropped_as(self, crop: bool) -> 'ImageRequest':
		return self.__class__(self._pictured, back=self._back, crop=crop)

	def __hash__(self) -> int:
		return hash(
			(
				self._pictured,
				self._pictured_type,
				self._pictured_name,
				self._back,
				self._crop,
			)
		)

	def __eq__(self, other) -> bool:
		return (
			isinstance(other, self.__class__)
			and self._pictured == other._pictured
			and self._pictured_type == other._pictured_type
			and self._pictured_name == other._pictured_name
			and self._back == other._back
			and self._crop == other._crop
		)

	def __repr__(self) -> str:
		if self._pictured_name is not None:
			return '{}({}, {})'.format(
				self.__class__.__name__,
				self._pictured_type,
				self._pictured_name,
			)

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
		pictured: pictureable = None,
		*,
		pictured_type: t.Union[t.Type[Printing], t.Type[Imageable]] = Printing,
		picture_name: t.Optional[str] = None,
		back: bool = False,
		crop: bool = False,
		save: bool = True,
		image_request: ImageRequest = None,
	) -> Promise:
		pass

	def get_default_image(self) -> Promise:
		pass

	@lru_cache(maxsize=256)
	def open_image(self, path: str) -> Image.Image:
		try:
			image = Image.open(path)
			image.load()
			return image
		except Exception as e:
			raise ImageFetchException(e)
