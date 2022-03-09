from typing import List
from threading import Thread, Lock
import requests
import time
import json
import logging
from datetime import date

from dotenv import load_dotenv

from Scraper import Scraper
from Reporter import Reporter
from Setting import Setting
from SoupParser import SoupParser
from SharedList import SharedList

import logging
import sys

logging.basicConfig(stream=sys.stdout, level=logging.INFO)
load_dotenv()
_logger = logging.getLogger(__name__)

# DEV = os.getenv('DEV')
DEV = 1

PROD_API_UPDATE_PLAN_URL = 'https://watplan.eu.pythonanywhere.com/Plan/update_schedule/'
DEV_API_UPDATE_PLAN_URL = 'http://127.0.0.1:8000/Plan/update_schedule/'
API_UPDATE_PLAN_URL = DEV_API_UPDATE_PLAN_URL if DEV else PROD_API_UPDATE_PLAN_URL

KEEP_CONNECTION_DELAY = 0.25

SECOND_SEMESTER_START = 3
FIRST_SEMESTER_START = 9


class Runner():

    def __init__(self, max_scraping_workers=3):
        self.max_scraping_workers = max_scraping_workers

        self.session = None
        self.scrapeLock = Lock()
        self.reporter = Reporter()
        self.setting_list = SharedList()
        self.soup_data = SharedList()
        self.schedule_data = SharedList()

    @classmethod
    def run_for_semester(cls, year: str, semester: str) -> None:
        sid = Scraper.authenticate()
        SETTING = {
            Setting.SID: sid,
            Setting.YEAR: year,
            Setting.SEMESTER: semester,
        }

        group_names = Scraper.get_group_names(Setting(**SETTING))
        settings = [Setting(group=group, **SETTING) for group in group_names]

        runner = cls()
        with requests.Session() as session:
            runner.session = session
            runner.run(settings)
        runner.reporter.report()

    @Reporter.time_measure
    def run(self, setting_list: List[Setting]) -> None:
        self.reset(setting_list)
        scraping_workers = min(self.max_scraping_workers, self.setting_list.length)

        jobs = [
            (self.__scrape, lambda: self.keep_scraping, scraping_workers),
            (self.__parse, lambda: self.keep_parsing, 1),
            (self.__post, lambda: self.keep_posting, 1)
        ]

        threads = [
            Thread(target=Runner.repeat, args=args)
            for *args, count in jobs for _ in range(count)
        ]

        tasks = [lambda thread: thread.start(), lambda thread: thread.join()]
        for thread in threads:
            for task in tasks:
                task(thread)

    def reset(self, setting_list: List[Setting]):
        self.reporter.reset()
        self.soup_data.reset()
        self.schedule_data.reset()
        self.setting_list.reset(setting_list)
        self.settings_count = len(setting_list)

    @staticmethod
    def repeat(func, predicate, *args, **kwargs):
        while predicate():
            func(*args, **kwargs)
        _logger.info(f'FINISHED {func.__name__} ')

    @Reporter.observe
    def __scrape(self) -> None:
        with self.scrapeLock:
            setting = self.setting_list.pop()
            time.sleep(KEEP_CONNECTION_DELAY)
        url = Scraper.get_group_url(setting)
        soup = Scraper.get_soup(url, self.session)

        assert soup and soup.title and 'e-Dziekanat' in soup.title.text, 'Invalid soup'
        self.soup_data.append((setting, soup))

    @Reporter.observe
    def __parse(self) -> None:
        setting, soup = self.soup_data.pop()
        group_schedule = SoupParser.get_group_schedule(
            setting=setting, soup=soup)
        self.schedule_data.append(group_schedule)

    @Reporter.observe
    def __post(self) -> None:
        group_schedule = self.schedule_data.pop()
        json_data = json.dumps(group_schedule)
        res = requests.post(
            url=API_UPDATE_PLAN_URL,
            headers={'Content-type': 'application/json'},
            data=json_data
        )
        _logger.info(f'DJANGO {res}')

    @property
    def keep_scraping(self):
        return self.setting_list.length > 0

    @property
    def keep_parsing(self):
        return (self.settings_count -
                self.reporter.get(self.__scrape).failed -
                self.reporter.get(self.__parse).finished > 0)

    @property
    def keep_posting(self):
        return (self.settings_count -
                self.reporter.get(self.__scrape).failed -
                self.reporter.get(self.__parse).failed -
                self.reporter.get(self.__post).finished > 0)


if __name__ == '__main__':
    today = date.today()
    semester = (SECOND_SEMESTER_START <= today.month <= FIRST_SEMESTER_START) + 1
    year = today.year - (semester == 2)
    Runner.run_for_semester(year=str(year), semester=str(semester))
