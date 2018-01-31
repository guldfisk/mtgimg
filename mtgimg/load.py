import os
import tempfile
import typing as t
from concurrent.futures import Executor, ThreadPoolExecutor
from functools import lru_cache
from threading import Condition, Lock

import requests as r
from PIL import Image
from promise import Promise

from mtgorp.models.persistent.attributes.layout import Layout
from mtgorp.models.persistent.printing import Printing

from mtgimg import paths
from mtgimg.request import ImageRequest
from mtgimg import crop as image_crop

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
	def _cropped_image(cls, condition: Condition, image: Image.Image, image_request: ImageRequest) -> Image.Image:
		if not os.path.exists(image_request.dir_path):
			os.makedirs(image_request.dir_path)
		cropped_image = image_crop.crop(image, image_request)
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
		self._executor = executor if executor is not None else ThreadPoolExecutor(max_workers=10)

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
				lambda : Loader.open_image(paths.CARD_BACK_PATH)
			)
		)
	@classmethod
	@lru_cache(maxsize=128)
	def open_image(cls, path):
		return Image.open(path)

def test():
	import time
	from mtgorp.db import load

	print(paths.IMAGES_PATH)

	image_loader = Loader()
	db = load.Loader.load()

	# cardboard = db.cardboards['Time Spiral']
	cardboard = db.cardboards['Fire // Ice']
	# printing = cardboard.from_expansion('USG')
	printing = cardboard.from_expansion('APC')
	print(printing, cardboard.printings)
	# printing_2 = cardboard.from_expansion('M14')

	st = time.time()

	images = [image_loader.get_image(printing, crop=True) for _ in range(10)]

	found_images = Promise.all(images).get()

	print('done', found_images, len(found_images), time.time() - st)

if __name__ == '__main__':
	test()