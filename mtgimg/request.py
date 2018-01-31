import os

from lazy_property import LazyProperty

from mtgorp.models.persistent.printing import Printing

from mtgimg import paths

class ImageRequest(object):
	def __init__(self, printing: Printing, back: bool = False, crop: bool = False):
		self._printing = printing
		self._back = back
		self._crop = crop
	@LazyProperty
	def has_image(self) -> bool:
		if self._back:
			return bool(self._printing.cardboard.back_cards)
		else:
			return bool(self._printing.cardboard.front_cards)
	def _name_no_extension(self) -> str:
		if self._back:
			if self.has_image:
				return str(self._printing.id) + 'b'
			return 'cardback'
		return str(self._printing.id)
	@property
	def name(self) -> str:
		return self._name_no_extension() + ('_crop' if self._crop else '')
	@property
	def extension(self) -> str:
		return 'png'
	@LazyProperty
	def dir_path(self) -> str:
		if self.has_image:
			return os.path.join(
				paths.IMAGES_PATH,
				self._printing.expansion.code,
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
		return 'https://api.scryfall.com/cards/multiverse/{}'.format(self.printing.id)
	@property
	def printing(self) -> Printing:
		return self._printing
	@property
	def back(self) -> bool:
		return self._back
	@property
	def crop(self) -> bool:
		return self._crop
	def cropped_as(self, crop: bool) -> 'ImageRequest':
		return self.__class__(self._printing, self._back, crop)
	def __hash__(self) -> int:
		return hash(
			(
				self._printing,
				self._back,
				self._crop,
			)
		)
	def __eq__(self, other) -> bool:
		return (
			isinstance(other, self.__class__)
			and self._printing == other._printing
			and self._back == other._back
			and self._crop == other._crop
		)
	def __repr__(self) -> str:
		return '{}({}, {}, {})'.format(
			self.__class__.__name__,
			self._printing,
			self._back,
			self._crop,
		)
