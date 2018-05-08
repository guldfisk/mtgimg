import typing as t

from PIL import Image

from mtgorp.models.persistent.attributes.layout import Layout
from mtgorp.models.persistent.attributes.cardtypes import CardSubType

from mtgimg.request import ImageRequest


CROPPED_SIZE = (560, 435)


def _split_horizontal(width: int, height: int, images: t.Tuple[Image.Image, ...]):
	offset = width // len(images)

	canvas = Image.new(
		'RGBA',
		(width, height),
		(0, 0, 0, 0),
	)

	for index, image in enumerate(images):
		canvas.paste(
			image.crop((0, 0, offset, height)),
			(index*offset, 0, (index+1)*offset, height)
		)

	return canvas


def _crop_standard(image: Image.Image) -> Image.Image:
	return image.crop(
		(92, 120, 652, 555)
	)


def _crop_split(image: Image.Image) -> Image.Image:
	return _split_horizontal(
		CROPPED_SIZE[0],
		CROPPED_SIZE[1],
		tuple(
			image.crop(box).rotate(-90, expand=1).resize((650, 435))
			for box in
			(
				(96, 82, 345, 454),
				(96, 582, 345, 954),
			)
		),
	)


def _crop_aftermath(image: Image.Image) -> Image.Image:
	top = image.crop((92, 120, 652, 332))
	bot = image.crop((408, 590, 620, 950))

	top.paste(
		bot.rotate(90, expand=1),
		(top.width // 2, 0)
	)

	return top.resize((1149, 435)).crop((294, 0, 854, 435))


def _crop_sage(image: Image.Image) -> Image.Image:
	return (
		image
			.crop((373, 115, 686, 872))
			.rotate(-90, expand=1)
			.resize((1052, 435))
			.crop((246, 0, 806, 435))
	)


SAGA_SUB_TYPE = CardSubType('Saga')


def crop(image: Image.Image, image_request: ImageRequest) -> Image.Image:
	layout = image_request.printing.cardboard.layout

	if layout == Layout.SAGA or SAGA_SUB_TYPE in image_request.printing.cardboard.front_card.card_type.sub_types:
		return _crop_sage(image)

	elif layout == Layout.STANDARD:
		return _crop_standard(image)

	elif layout == Layout.SPLIT and len(image_request.printing.cardboard.front_cards) == 2:
		return _crop_split(image)

	elif layout == Layout.AFTERMATH and len(image_request.printing.cardboard.front_cards) == 2:
		return _crop_aftermath(image)

	else:
		return _crop_standard(image)

