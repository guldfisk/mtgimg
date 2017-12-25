import threading
import os
import typing as t
import requests as r
import tempfile

from PIL import Image
from functools import lru_cache

from promise import Promise
from appdirs import AppDirs
from lazy_property import LazyProperty

from mtgorp.models.persistent.printing import Printing
from mtgorp.models.persistent.attributes.layout import Layout

from mtgimg.async import Resolver

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
	def remote_card_uri(self) -> str:
		return 'https://api.scryfall.com/cards/multiverse/{}'.format(self.printing.id)
	@property
	def printing(self):
		return self._printing
	@property
	def back(self):
		return self._back
	@property
	def crop(self):
		return self._crop
	def cropped_as(self, crop: bool):
		return self.__class__(self._printing, self._back, crop)
	def __hash__(self):
		return hash((
			self._printing,
			self._back,
			self._crop,
		))
	def __eq__(self, other):
		return (
			isinstance(other, self.__class__)
			and self._printing == other._printing
			and self._back == other._back
			and self._crop == other._crop
		)
	def __repr__(self):
		return '{}({}, {}, {})'.format(
			self.__class__.__name__,
			self._printing,
			self._back,
			self._crop,
		)


class SingleAccessDict(dict):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self._lock = threading.Lock()
	def __getitem__(self, item):
		with self._lock:
			return super().__getitem__(item)
	def __setitem__(self, key, value):
		with self._lock:
			super().__setitem__(key, value)
	def __delitem__(self, key):
		with self._lock:
			super().__delitem__(key)
	def get(self, key, default = None):
		with self._lock:
			return super().get(key, default)

class ImageFetchException(Exception):
	pass

class Fetcher(Resolver):
	_fetching = SingleAccessDict()

	def __init__(
		self,
		image_request: ImageRequest,
		size: t.Tuple[int, int] = (745, 1040)
	):
		super().__init__()
		self._image_request = image_request
		self._size = size
		
	def run(self):
		try:
			remote_card_response = r.get(self._image_request.remote_card_uri)
		except Exception:
			self._reject(ImageFetchException())
			return
		if not remote_card_response.ok:
			self._reject(ImageFetchException())
			return
		
		remote_card = remote_card_response.json()
		try:
			image_response = r.get(
				remote_card['card_faces'][-1 if self._image_request.back else 0]['image_uris']['png']
				if self._image_request.printing.cardboard.layout == Layout.TRANSFORM else
				remote_card['image_uris']['png'],
				stream=True,
			)
		except Exception:
			self._reject(ImageFetchException())
			return
		if not image_response.ok:
			self._reject(ImageFetchException())
			return
		
		if not os.path.exists(self._image_request.dir_path):
			os.makedirs(self._image_request.dir_path)

		with tempfile.NamedTemporaryFile() as temp_file:
			for chunk in image_response.iter_content(1024):
				temp_file.write(chunk)
			fetched_image = Image.open(temp_file)
			if not fetched_image.size == self._size:
				fetched_image = fetched_image.resize(self._size)
				fetched_image.save(
					self._image_request.path,
					self._image_request.extension,
				)
			else:
				os.link(
					temp_file.name,
					self._image_request.path,
				)
			self._resolve(Image.open(self._image_request.path))

	def get_promise(self):
		print('fetcher get promise')
		try:
			image = Loader.open_image(self._image_request.path)
			print('image loaded', image)
			return Promise(
				lambda resolve, reject:
					resolve(image)
			)
		except FileNotFoundError:
			print('file not found, fetching')
			existing_promise = Fetcher._fetching.get(self._image_request, None)
			if existing_promise is None:
				promise = Promise(self)
				Fetcher._fetching[self._image_request] = promise
				return promise
			existing_promise.then(self._resolve, self._reject)
			return existing_promise

class Cropper(object):
	@staticmethod
	def _crop_image(image: Image.Image, layout: Layout):
		if layout == Layout.STANDARD:
			return image.crop(
				(92, 120, 652, 555)
			)
		else:
			return image.crop(
				(92, 120, 652, 555)
			)
	@staticmethod
	def crop_image(image: Image.Image, image_request: ImageRequest) -> Image.Image:
		if not os.path.exists(image_request.dir_path):
			os.makedirs(image_request.dir_path)
		cropped_image = Cropper._crop_image(image, image_request.printing.cardboard.layout)
		cropped_image.save(image_request.path, 'png')
		return cropped_image
	@staticmethod
	def cropped_image(image_request: ImageRequest) -> Promise:
		try:
			image = Loader.open_image(image_request.path)
			return Promise(
				lambda resolve, reject:
					resolve(image)
			)
		except FileNotFoundError:
			return (
				Fetcher(image_request.cropped_as(False))
				.get_promise()
				.then(lambda v: Cropper.crop_image(v, image_request))
			)

class Loader(object):
	@classmethod
	def get_image(
		cls,
		printing: Printing = None,
		back: bool = False,
		crop: bool = False,
		image_request: ImageRequest = None,
	) -> Promise:
		_image_request = ImageRequest(printing, back, crop) if image_request is None else image_request
		if crop:
			return Cropper.cropped_image(_image_request)
		else:
			return Fetcher(_image_request).get_promise()
	@classmethod
	def get_default_image(cls):
		print('get default image')
		return Promise(lambda resolve, reject: resolve(Loader.open_image(CARD_BACK_PATH)))
	@classmethod
	# @lru_cache(maxsize=128)
	def open_image(cls, path):
		print('open image', path)
		return Image.open(path)

def test():
	from mtgorp.db import create, load
	db = load.Loader.load()
	# printing = db.cardboards['Fire // Ice'].printings.__iter__().__next__()
	cardboard = db.cardboards['Time Spiral']
	printing_1 = cardboard.from_expansion('USG')
	# printing_2 = cardboard.from_expansion('M14')

	image = Loader.get_image(printing_1)

	# printings = (printing_1, printing_2)
	#
	# images = Promise.all(tuple(Loader.get_image(printing) for printing in printings)).get()
	# print(images)

	# Loader.get_image(printing, crop = True, callback=t)

if __name__ == '__main__':
	test()