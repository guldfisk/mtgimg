import os
import os
import tempfile
import typing as t
from concurrent.futures import Executor, ThreadPoolExecutor
from functools import lru_cache
from threading import Condition, Lock

import requests as r
from PIL import Image
from appdirs import AppDirs
from lazy_property import LazyProperty
from promise import Promise

from mtgorp.models.persistent.attributes.layout import Layout
from mtgorp.models.persistent.printing import Printing

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
		return hash(
			(
				self._printing,
				self._back,
				self._crop,
			)
		)
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

class TaskAwaiter(object):
	def __init__(self):
		self._lock = Lock()
		self._map = dict() #type: t.Dict[ImageRequest, Condition]
	def get_condition(self, image_request: ImageRequest) -> t.Tuple[Condition, bool]:
		with self._lock:
			previous_condition = self._map.get(image_request, None)
			if previous_condition is None:
				condition = Condition()
				self._map[image_request] = condition
				return condition, False
			return previous_condition, True

class ImageFetchException(Exception):
	pass

class _Fetcher(object):
	_fetching = TaskAwaiter()
	_size = (745, 1040)

	@classmethod
	def _fetch_image(cls, condition: Condition, image_request: ImageRequest):

		try:
			remote_card_response = r.get(image_request.remote_card_uri)
		except Exception as e:
			raise ImageFetchException(e)
		if not remote_card_response.ok:
			raise ImageFetchException(remote_card_response.status_code)
		
		remote_card = remote_card_response.json()
		try:
			image_response = r.get(
				remote_card['card_faces'][-1 if image_request.back else 0]['image_uris']['png']
				if image_request.printing.cardboard.layout == Layout.TRANSFORM else
				remote_card['image_uris']['png'],
				stream=True,
			)
		except Exception as e:
			raise ImageFetchException(e)
		if not image_response.ok:
			raise ImageFetchException(remote_card_response.status_code)
		
		if not os.path.exists(image_request.dir_path):
			os.makedirs(image_request.dir_path)

		with tempfile.NamedTemporaryFile() as temp_file:
			for chunk in image_response.iter_content(1024):
				temp_file.write(chunk)
			fetched_image = Image.open(temp_file)
			if not fetched_image.size == cls._size:
				fetched_image = fetched_image.resize(cls._size)
				fetched_image.save(
					image_request.path,
					image_request.extension,
				)
			else:
				os.link(
					temp_file.name,
					image_request.path,
				)
			with condition:
				condition.notify_all()

	@classmethod
	def get_image(cls, image_request: ImageRequest):
		try:
			return Loader.open_image(image_request.path)
		except FileNotFoundError:
			condition, in_progress = cls._fetching.get_condition(image_request)
			if in_progress:
				with condition:
					condition.wait()
			else:
				cls._fetch_image(condition, image_request)
			return Loader.open_image(image_request.path)

class _Cropper(object):
	_cropping = TaskAwaiter()

	@classmethod
	def _crop_image(cls, image: Image.Image, layout: Layout) -> Image.Image:
		if layout == Layout.STANDARD:
			return image.crop(
				(92, 120, 652, 555)
			)
		else:
			return image.crop(
				(92, 120, 652, 555)
			)
	@classmethod
	def _cropped_image(cls, condition: Condition, image: Image.Image, image_request: ImageRequest) -> Image.Image:
		if not os.path.exists(image_request.dir_path):
			os.makedirs(image_request.dir_path)
		cropped_image = _Cropper._crop_image(image, image_request.printing.cardboard.layout)
		cropped_image.save(image_request.path, image_request.extension)
		with condition:
			condition.notify_all()
		return cropped_image
	@classmethod
	def cropped_image(cls, image_request: ImageRequest) -> Image.Image:
		try:
			return Loader.open_image(image_request.path)
		except FileNotFoundError:
			condition, in_progress = cls._cropping.get_condition(image_request)
			if in_progress:
				with condition:
					condition.wait()
				return Loader.open_image(image_request.path)
			else:
				return cls._cropped_image(
					condition,
					_Fetcher.get_image(image_request.cropped_as(False)),
					image_request,
				)



class Loader(object):
	def __init__(self, executor: Executor = None):
		self._executor = executor if executor is not None else ThreadPoolExecutor(max_workers=5)

	def get_image(
		self,
		printing: Printing = None,
		back: bool = False,
		crop: bool = False,
		image_request: ImageRequest = None,
	) -> Promise:
		_image_request = ImageRequest(printing, back, crop) if image_request is None else image_request
		if _image_request.crop:
			return Promise.resolve(self._executor.submit(_Cropper.cropped_image, _image_request))
		else:
			return Promise.resolve(self._executor.submit(_Fetcher.get_image, _image_request))
	def get_default_image(self):
		return Promise.resolve(
			self._executor.submit(
				lambda : Loader.open_image(CARD_BACK_PATH)
			)
		)
	@classmethod
	@lru_cache(maxsize=128)
	def open_image(cls, path):
		return Image.open(path)

def test():
	import time
	from mtgorp.db import load

	print(IMAGES_PATH)

	image_loader = Loader()
	db = load.Loader.load()

	cardboard = db.cardboards['Time Spiral']
	printing = cardboard.from_expansion('USG')
	# printing_2 = cardboard.from_expansion('M14')

	st = time.time()

	images = [image_loader.get_image(printing, crop=True) for _ in range(10)]

	found_images = Promise.all(images).get()

	print('done', found_images, len(found_images), time.time() - st)

if __name__ == '__main__':
	test()