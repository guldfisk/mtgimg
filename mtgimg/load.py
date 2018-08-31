import typing as t

import os
from concurrent.futures import Executor, ThreadPoolExecutor
from threading import Condition, Lock

import requests as r
from PIL import Image
from promise import Promise

from mtgorp.models.persistent.attributes.layout import Layout

from mtgimg import paths
from mtgimg.interface import ImageRequest, Imageable, ImageLoader, picturable
from mtgimg import crop as image_crop


IMAGE_SIZE = (745, 1040)
CROPPED_IMAGE_SIZE = (560, 435)

IMAGE_WIDTH, IMAGE_HEIGHT = IMAGE_SIZE

CROPPED_IMAGE_WIDTH, CROPPED_IMAGE_HEIGHT = CROPPED_IMAGE_SIZE


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


class _ImageableProcessor(object):
	_processing = TaskAwaiter()

	@classmethod
	def _save_imageable(
		cls,
		image_request: ImageRequest,
		size: t.Tuple[int, int],
		loader: ImageLoader,
		condition: Condition
	) -> Image.Image:

		image = image_request.pictured.get_image(
			size,
			loader,
			image_request.back,
			image_request.crop,
		)

		if image.size != size:
			image = image.resize(size)

		if not os.path.exists(image_request.dir_path):
			os.makedirs(image_request.dir_path)

		image.save(image_request.path)

		with condition:
			condition.notify_all()

		return image

	@classmethod
	def get_image(cls, image_request: ImageRequest, loader: ImageLoader):
		try:
			return Loader.open_image(image_request.path)
		except FileNotFoundError:
			pass

		condition, in_progress = cls._processing.get_condition(image_request)

		if in_progress:
			with condition:
				condition.wait()

			return Loader.open_image(image_request.path)

		return cls._save_imageable(
			image_request,
			CROPPED_IMAGE_SIZE if image_request.crop else IMAGE_SIZE,
			loader,
			condition,
		)


class _Fetcher(object):
	_fetching = TaskAwaiter()
	_size = IMAGE_SIZE

	@classmethod
	def _fetch_image(cls, condition: Condition, image_request: ImageRequest):
		try:
			remote_card_response = r.request('GET', image_request.remote_card_uri, timeout = 30)
		except Exception as e:
			raise ImageFetchException(e)

		if not remote_card_response.ok:
			raise ImageFetchException(remote_card_response.status_code)
		
		remote_card = remote_card_response.json()

		try:
			if image_request.pictured.cardboard.layout == Layout.MELD and image_request.back:
				for part in remote_card['all_parts']:
					if part['name'] == image_request.pictured.cardboard.back_card.name:
						remote_card = r.request('GET', part['uri'], timeout = 30).json()

			image_response = r.request(
				'GET',
				remote_card['card_faces'][-1 if image_request.back else 0]['image_uris']['png']
				if image_request.pictured.cardboard.layout == Layout.TRANSFORM else
				remote_card['image_uris']['png'],
				stream=True,
				timeout = 30,
			)

		except Exception as e:
			raise ImageFetchException(e)

		if not image_response.ok:
			raise ImageFetchException(remote_card_response.status_code)
		
		if not os.path.exists(image_request.dir_path):
			os.makedirs(image_request.dir_path)

		temp_path = os.path.join(image_request.dir_path, '_' + image_request.name + '.' + image_request.extension)

		with open(temp_path, 'wb') as temp_file:
			for chunk in image_response.iter_content(1024):
				temp_file.write(chunk)

			with open(temp_path, 'rb') as f:
				fetched_image = Image.open(f)

			if not fetched_image.size == cls._size:
				fetched_image = fetched_image.resize(cls._size)
				fetched_image.save(
					image_request.path,
					image_request.extension,
				)
			else:
				os.rename(temp_path, image_request.path)

		# Hard link rekked
		# with tempfile.NamedTemporaryFile() as temp_file:
		# 	for chunk in image_response.iter_content(1024):
		# 		temp_file.write(chunk)
		#
		# 	fetched_image = Image.open(temp_file)
		# 	if not fetched_image.size == cls._size:
		# 		fetched_image = fetched_image.resize(cls._size)
		# 		fetched_image.save(
		# 			image_request.path,
		# 			image_request.extension,
		# 		)
		# 	else:
		# 		os.link(
		# 			temp_file.name,
		# 			image_request.path,
		# 		)

		with condition:
			condition.notify_all()

	@classmethod
	def get_image(cls, image_request: ImageRequest) -> Image.Image:

		try:
			return Loader.open_image(image_request.path)
		except FileNotFoundError:
			if not image_request.has_image:
				raise ImageFetchException('Missing default image')

		condition, in_progress = cls._fetching.get_condition(image_request)

		if in_progress:
			with condition:
				condition.wait()
		else:
			cls._fetch_image(condition, image_request)

		return Loader.open_image(image_request.path)


class _Cropper(object):
	_size = CROPPED_IMAGE_SIZE
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
			pass

		condition, in_progress = cls._cropping.get_condition(image_request)

		if in_progress:
			with condition:
				condition.wait()
			return Loader.open_image(image_request.path)

		return cls._cropped_image(
			condition,
			_Fetcher.get_image(image_request.cropped_as(False)),
			image_request,
		)


class Loader(ImageLoader):

	def __init__(
		self,
		printing_executor: t.Union[Executor, int] = None,
		imageable_executor: t.Union[Executor, int] = None
	):
		self._printings_executor = (
			printing_executor
			if printing_executor is isinstance(printing_executor, Executor) else
			ThreadPoolExecutor(
				max_workers = printing_executor if isinstance(printing_executor, int) else 10
			)
		)

		self._imageables_executor = (
			imageable_executor
			if imageable_executor is isinstance(imageable_executor, Executor) else
			ThreadPoolExecutor(
				max_workers = imageable_executor if isinstance(imageable_executor, int) else 10
			)
		)

	def get_image(
		self,
		pictured: picturable = None,
		back: bool = False,
		crop: bool = False,
		image_request: ImageRequest = None,
	) -> Promise:
		_image_request = (
			ImageRequest(pictured, back, crop)
			if image_request is None else
			image_request
		)

		if isinstance(_image_request.pictured, Imageable):
			return Promise.resolve(
				self._imageables_executor.submit(
					_ImageableProcessor.get_image,
					_image_request,
					self,
				)
			)

		if _image_request.crop:
			return Promise.resolve(
				self._printings_executor.submit(
					_Cropper.cropped_image,
					_image_request,
				)
			)

		else:
			return Promise.resolve(
				self._printings_executor.submit(
					_Fetcher.get_image,
					_image_request,
				)
			)

	def get_default_image(self) -> Promise:
		return Promise.resolve(
			self._printings_executor.submit(
				lambda : Loader.open_image(paths.CARD_BACK_PATH)
			)
		)

