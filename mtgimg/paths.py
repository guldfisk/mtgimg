import os

from appdirs import AppDirs


APP_DATA_PATH = AppDirs("mtgimg", "mtgimg").user_data_dir

try:
    with open(os.path.join(APP_DATA_PATH, "imagepath.txt"), "r") as f:
        IMAGES_PATH = f.read().strip()
except FileNotFoundError:
    IMAGES_PATH = os.path.join(APP_DATA_PATH, "images")

CARD_BACK_DIRECTORY_PATH = os.path.join(
    os.path.dirname(os.path.realpath(__file__)),
    "cardback",
)

CARD_BACK_PATH = os.path.join(
    CARD_BACK_DIRECTORY_PATH,
    "cardback.png",
)

MEDIUM_CARD_BACK_PATH = os.path.join(
    CARD_BACK_DIRECTORY_PATH,
    "cardback_m.png",
)

SMALL_CARD_BACK_PATH = os.path.join(
    CARD_BACK_DIRECTORY_PATH,
    "cardback_s.png",
)

THUMBNAIL_CARD_BACK_PATH = os.path.join(
    CARD_BACK_DIRECTORY_PATH,
    "cardback_t.png",
)
