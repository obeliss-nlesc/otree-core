# like common, but can import models
import importlib.util
import os
import time
from dataclasses import dataclass, asdict
from pathlib import Path

from starlette.staticfiles import StaticFiles

from otree import settings
from otree.database import db
from otree.models_concrete import PageTimeBatch


@dataclass
class TimeSpentRow:
    session_code: str
    participant_id_in_session: int
    participant_code: str
    page_index: int
    app_name: str
    page_name: str
    epoch_time_completed: int
    round_number: int
    timeout_happened: int
    is_wait_page: int


page_completion_buffer = []
page_completion_last_write = 0

BUFFER_SIZE = 50


def write_row_to_page_buffer(row: TimeSpentRow):
    d = asdict(row)
    row = ','.join(map(str, d.values())) + '\n'

    page_completion_buffer.append(row)
    if (
        len(page_completion_buffer) > BUFFER_SIZE
        or time.time() - page_completion_last_write > 60 * 2
    ):
        write_page_completion_buffer()


def make_page_completion_row(
    *,
    view,
    app_name,
    participant__id_in_session,
    participant__code,
    session_code,
    is_wait_page,
):
    now = int(time.time())
    row = TimeSpentRow(
        app_name=app_name,
        page_index=view._index_in_pages,
        page_name=type(view).__name__,
        epoch_time_completed=now,
        round_number=view.round_number,
        participant_id_in_session=participant__id_in_session,
        participant_code=participant__code,
        session_code=session_code,
        timeout_happened=int(bool(getattr(view, 'timeout_happened', False))),
        is_wait_page=is_wait_page,
    )
    write_row_to_page_buffer(row)


def write_page_completion_buffer():
    global page_completion_last_write
    db.add(PageTimeBatch(text=''.join(page_completion_buffer)))
    page_completion_last_write = time.time()
    page_completion_buffer.clear()


class OTreeStaticFiles(StaticFiles):
    # copied from starlette, just to change 'statics' to 'static',
    # and to fail silently if the dir does not exist.
    def get_directories(self, directory, packages):
        directories = []
        if directory is not None:
            directories.append(directory)

        for package in packages or []:
            spec = importlib.util.find_spec(package)
            assert (
                spec is not None and spec.origin is not None
            ), f"Package {package!r} could not be found, or maybe __init__.py is missing"
            package_directory = os.path.normpath(
                os.path.join(spec.origin, "..", "static")
            )
            if os.path.isdir(package_directory):
                directories.append(package_directory)

        return directories

    def assert_file_exists(self, path):
        if path in existing_filenames_cache:
            return
        for _dir in self.all_directories:
            if Path(_dir, path).is_file():
                existing_filenames_cache.add(path)
                return
        raise FileNotFoundError(path)

    def urls_of_static_files(self, dirpath, extension):
        from otree.asgi import app

        if extension.startswith('.'):
            raise Exception("Extension should not contain a dot")

        for root in self.all_directories:
            _dir = Path(root, dirpath)
            if _dir.is_dir():
                for _file in _dir.glob(f'*.{extension}'):
                    relpath = _file.relative_to(root)
                    yield app.router.url_path_for('static', path=relpath)


existing_filenames_cache = set()


def url_of_static_file(path):
    """
    - better than hardcoding '/static/', which will fail silently if the file
    doesn't exist.
    - there is the {{ static }} tag in templates.
      good to have this in python code for consistency,
      rather than making people construct it manually.
    - useful for:
        - Trials, which are generated on the server side.
          this would be useful for 2 situations:
        - live pages, where {% static %} can't be used because the template was already rendered
        - js_vars (don't want {% static %} mixed in with JS code)

    naming:
    - it shouldn't start with
    'static' because that would distract from @staticmethod in autocomplete,
    which is much more important.
    - url_of_static is more specific than url_for_static (which looks like vars_for_template but works differently)

    """
    from otree.asgi import app

    static_files_app.assert_file_exists(path)
    return app.router.url_path_for('static', path=path)


def urls_of_static_files(dir, extension):
    """
    e.g.:
    >>> urls_of_static_files('emojis', 'png')
    ['/static/emojis/1.png', '/static/emojis/2.png']

    I don't know how useful this would be because usually people have (a) some metadata about the file,
    such as what it contains. also for DB storage & record-keeping,
    people would want to store the filename, e.g. '1.png',
    rather than the full URL path, e.g. '/static/emojis/1.png'

    But if we see a lot of people just trying to include all images in a dir,
    then we can add this to API.
    """
    return static_files_app.urls_of_static_files(dir, extension)


static_files_app = OTreeStaticFiles(
    directory='_static', packages=['otree'] + settings.OTREE_APPS
)
