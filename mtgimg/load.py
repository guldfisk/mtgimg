import threading
import os
import typing as t
import requests as r
import copy

from functools import lru_cache
from PIL import Image

from appdirs import AppDirs
from lazy_property import LazyProperty

from mtgorp.models.persistent.printing import Printing
from mtgorp.models.persistent.attributes.layout import Layout

APP_DATA_PATH = AppDirs('mtgimg', 'mtgimg').user_data_dir
IMAGES_PATH = os.path.join(APP_DATA_PATH, 'images')
CARD_BACK_DIRECTORY_PATH = os.path.join(
	os.path.dirname(os.path.realpath(__file__)),
	'cardback',
)
CARD_BACK_PATH = os.path.join(
	CARD_BACK_DIRECTORY_PATH,
	'cardback.png',
)

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
				return str(self._printing.collector_number) + 'b'
			return 'cardback'
		if len(tuple(self._printing.cardboard.cards))>1:
			return str(self._printing.collector_number) + 'a'
		return str(self._printing.collector_number)
	@LazyProperty
	def name(self) -> str:
		return self._name_no_extension() + ('_crop' if self._crop else '')
	@property
	def extension(self) -> str:
		return 'png'
	@LazyProperty
	def dir_path(self) -> str:
		if self.has_image:
			return os.path.join(
				IMAGES_PATH,
				self._printing.expansion.code,
			)
		return CARD_BACK_DIRECTORY_PATH
	@LazyProperty
	def path(self) -> str:
		return os.path.join(
			self.dir_path,
			self.name + '.' + self.extension,
		)
	@LazyProperty
	def uri(self) -> str:
		return 'https://img.scryfall.com/cards/{}/en/{}/{}.{}'.format(
			'art_crop' if self._crop else 'png',
			self._printing.expansion.code.lower(),
			self._name_no_extension(),
			self.extension
		)
	def __hash__(self):
		return hash((
			self._printing,
			self._back,
			self._crop,
		))
	def __eq__(self, other):
		return isinstance(other, self.__class__)\
			and self._printing == other._printing\
			and self._back == other._back\
			and self._crop == other._crop

class SingleAccessDict(dict):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.lock = threading.Lock()
	def __getitem__(self, item):
		with self.lock:
			v = super().__getitem__(item)
		return v
	def __setitem__(self, key, value):
		with self.lock:
			super().__setitem__(key, value)
	def __delitem__(self, key):
		with self.lock:
			super().__delitem__(key)

class Fetcher(threading.Thread):
	fetching = SingleAccessDict()
	def __init__(
		self,
		image_request: ImageRequest,
		callback: t.Callable = None,
		size: t.Tuple[int, int] = (745, 1040)
	):
		super().__init__()
		self.image_request = image_request
		self.callback = callback
		self.size = size
	@staticmethod
	def _fetch(image_request: ImageRequest, size: t.Tuple[int, int]):
		print('fetching', image_request, image_request.uri)
		ro = r.get(
			image_request.uri,
			stream=True,
		)
		temp_path = os.path.join(image_request.dir_path, 'temp')
		if not ro.ok:
			return
		with open(temp_path, 'wb') as f:
			for chunk in ro.iter_content(1024):
				f.write(chunk)
		fetched_image = Image.open(temp_path)
		fetched_image.load()
		if not fetched_image.size == size:
			fetched_image = fetched_image.resize(size)
			fetched_image.save(temp_path, image_request.extension)
		os.rename(
			temp_path,
			image_request.path,
		)
		return Image.open(image_request.path)
	@staticmethod
	def fetch(image_request: ImageRequest, callback: t.Callable = None, size: t.Tuple[int, int] = (745, 1040)):
		if image_request in Fetcher.fetching:
			if callback is not None:
				Fetcher.fetching[image_request].append(callback)
			return
		Fetcher.fetching[image_request] = [callback] if callback is not None else []

		if not os.path.exists(image_request.dir_path):
			os.makedirs(image_request.dir_path)

		result = Fetcher._fetch(image_request, size)

		for subscibed_callback in Fetcher.fetching[image_request]:
			subscibed_callback(image_request, result)
		del Fetcher.fetching[image_request]
	def run(self):
		Fetcher.fetch(
			image_request= self.image_request,
			callback = self.callback,
			size = self.size,
		)

class Cropper(threading.Thread):
	cropping = SingleAccessDict()
	def __init__(self, image_request: ImageRequest, callback: t.Callable = None, size: t.Tuple[int, int] = (0, 0)):
		super().__init__()
		print(image_request)
		self.image_request = image_request
		self.image_request._crop = True
		self.callback = callback
		self.size = size
	@staticmethod
	def cropped_image(image_request: ImageRequest):
		img = Loader.get_image(
			printing = image_request._printing,
			back = image_request._back,
			async = False,
		)
		return Cropper._cropped_image(
			image = img,
			layout = image_request._printing.cardboard.layout,
		)
	@staticmethod
	def _cropped_image(image: Image.Image, layout: Layout):
		if layout == Layout.STANDARD:
			return image.crop(
				(92, 120, 652, 555)
			)
		else:
			return image.crop(
				(92, 120, 652, 555)
			)

	@staticmethod
	def _crop(image_request: ImageRequest):
		uncropped_request = copy.copy(image_request)
		uncropped_request._crop = False
		Cropper.cropped_image(uncropped_request).save(
			image_request.path,
			image_request.extension
		)
		return Image.open(image_request.path)
	@staticmethod
	def crop(image_request: ImageRequest, callback: t.Callable = None):
		if image_request in Cropper.cropping:
			if callback is not None:
				Cropper.cropping[image_request].append(callback)
			return
		Cropper.cropping[image_request] = [callback] if callback is not None else []

		if not os.path.exists(image_request.dir_path):
			os.makedirs(image_request.dir_path)

		result = Cropper._crop(image_request)

		for subscibed_callback in Cropper.cropping[image_request]:
			subscibed_callback(image_request, result)
		del Cropper.cropping[image_request]
	def run(self):
		self.crop(
			image_request = self.image_request,
			callback = self.callback,
		)

class Loader(object):
	@classmethod
	def get_image(
		cls,
		printing: Printing = None,
		back: bool = False,
		crop: bool = False,
		callback: t.Callable = None,
		async: bool = True,
		image_request: ImageRequest = None,
	) -> Image.Image:
		_image_request = ImageRequest(printing, back, crop) if image_request is None else image_request
		try:
			return cls._get_image(_image_request.path)
		except FileNotFoundError:
			if crop:
				if async:
					Cropper(_image_request, callback).start()
					return cls._get_image(CARD_BACK_PATH)
				else:
					Cropper(_image_request).run()
			else:
				if async:
					Fetcher(_image_request, callback).start()
					return cls._get_image(CARD_BACK_PATH)
				else:
					Fetcher(_image_request).run()
		return cls._get_image(_image_request.path)
	@classmethod
	@lru_cache(maxsize=128)
	def _get_image(cls, path: str) -> Image.Image:
		return Image.open(path)

def test():
	from mtgorp.db import create, load
	db = load.Loader.load()
	# printing = db.cardboards['Fire // Ice'].printings.__iter__().__next__()
	cardboard = db.cardboards['Delver of Secrets // Insectile Aberration']
	# printing = db.printings[(db.expansions['CMD'], '198')]
	printing = cardboard.printings.__iter__().__next__()
	print(printing)

	def t(q, r):
		print('callback', q._printing, r)

	Loader.get_image(printing, crop = True, callback=t, back=True)
	Loader.get_image(printing, crop = True, callback=t)

if __name__ == '__main__':
	test()