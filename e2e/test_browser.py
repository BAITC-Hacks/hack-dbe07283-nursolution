"""Изолированный офлайн-сервер и новый профиль браузера; рабочий сервер не меняется."""
import os
import re
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen
from unittest import TestCase, skipUnless
from uuid import uuid4
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]


class BrowserTests(TestCase):
    backend = "csv"
    @classmethod
    def setUpClass(cls):
        cls.output=ROOT/'test-results'; cls.output.mkdir(exist_ok=True)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
        cls.base=f'http://127.0.0.1:{port}'
        env={**os.environ,'MATCHER_USE_LLM':'false','OPENAI_API_KEY':'','CATALOG_BACKEND':'csv','MATCHER_CSV_PATH':'','ADMIN_TOKEN':'e2e-local-editor'}
        if cls.backend == 'postgres':
            cls.schema='nur_e2e_'+uuid4().hex
            with psycopg.connect(os.environ['POSTGRES_TEST_URL']) as conn:
                conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(cls.schema)))
            cls.addClassCleanup(cls.drop_schema)
            env['CATALOG_BACKEND']='postgres'
            env['DATABASE_URL']=make_conninfo(os.environ['POSTGRES_TEST_URL'], options=f'-csearch_path={cls.schema}')
        cls.log=(cls.output/(cls.backend+'-server.log')).open('w',encoding='utf-8')
        cls.addClassCleanup(cls.log.close)
        cls.server=subprocess.Popen([sys.executable,'-m','uvicorn','api:app','--host','127.0.0.1','--port',str(port)],cwd=ROOT,env=env,stdout=cls.log,stderr=subprocess.STDOUT)
        cls.addClassCleanup(cls.stop_server)
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            if cls.server.poll() is not None: raise RuntimeError('E2E server exited; see test-results/server.log')
            try:
                with urlopen(cls.base+'/health',timeout=1): break
            except OSError: time.sleep(.1)
        else: raise RuntimeError('E2E server startup timed out')
        cls.playwright=sync_playwright().start();cls.addClassCleanup(cls.playwright.stop)
        channel=os.getenv('E2E_BROWSER_CHANNEL')
        cls.browser=cls.playwright.chromium.launch(**({'channel':channel} if channel else {}))
        cls.addClassCleanup(cls.browser.close)

    @classmethod
    def drop_schema(cls):
        with psycopg.connect(os.environ['POSTGRES_TEST_URL']) as conn:
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(cls.schema)))

    @classmethod
    def stop_server(cls):
        cls.server.terminate()
        try: cls.server.wait(timeout=5)
        except subprocess.TimeoutExpired: cls.server.kill();cls.server.wait(timeout=5)

    def setUp(self):
        self.context=self.browser.new_context(viewport={'width':1360,'height':1000})
        self.addCleanup(self.context.close)
        self.page=self.context.new_page()
        self.errors=[]
        self.api_requests=[]
        self.match_requests=[]
        self.page.on('pageerror',lambda error:self.errors.append(str(error)))
        self.page.on('request',lambda request:self.api_requests.append(request)
                     if request.url.endswith(('/catalog','/match')) else None)
        self.page.on('request',lambda request:self.match_requests.append(request)
                     if request.url.endswith('/match') else None)
        self.page.goto(self.base+'/selection')
        expect(self.page.get_by_role('button',name='Подобрать людей',exact=True)).to_be_enabled()

    def tearDown(self):
        self.page.evaluate("window.scrollTo({top:0,left:0,behavior:'instant'})")
        self.page.screenshot(path=str(self.output/(self.backend+'-'+self._testMethodName+'.png')),full_page=True,animations='disabled')
        self.assertEqual(self.errors,[])

    def submit(self):
        with self.page.expect_response(lambda r:r.url.endswith('/match') and r.request.method=='POST'):
            self.page.get_by_role('button',name='Подобрать людей',exact=True).click()

    def test_homepage_waits_for_request(self):
        self.api_requests.clear()
        self.match_requests.clear()
        self.page.goto(self.base)
        expect(self.page.locator('#order-form')).to_have_count(0)
        expect(self.page.locator('#results-panel')).to_have_count(0)
        expect(self.page.get_by_role('link',name='Главная',exact=True).first).to_have_attribute('aria-current','page')
        self.assertEqual(self.api_requests,[])
        self.page.screenshot(path=str(self.output/(self.backend+'-homepage-desktop.png')),full_page=True,animations='disabled')
        self.page.set_viewport_size({'width':375,'height':812})
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),375)
        self.page.screenshot(path=str(self.output/(self.backend+'-homepage-mobile.png')),full_page=True,animations='disabled')
        self.assertEqual(self.api_requests,[])
        self.page.set_viewport_size({'width':1360,'height':1000})
        self.page.get_by_role('link',name='Подобрать подрядчиков',exact=True).first.click()
        expect(self.page).to_have_url(self.base+'/selection')
        expect(self.page.get_by_role('button',name='Подобрать людей',exact=True)).to_be_enabled()
        expect(self.page.get_by_role('link',name='Подбор',exact=True).first).to_have_attribute('aria-current','page')
        expect(self.page.locator('#results-panel')).to_be_hidden()
        expect(self.page.get_by_role('article')).to_have_count(0)
        self.assertEqual(len(self.api_requests),1)
        self.assertTrue(self.api_requests[0].url.endswith('/catalog'))
        self.assertEqual(self.match_requests,[])
        self.page.screenshot(path=str(self.output/(self.backend+'-selection-desktop.png')),full_page=True,animations='disabled')
        self.submit()
        expect(self.page.locator('#results-panel')).to_be_visible()
        expect(self.page.get_by_role('article')).to_have_count(3)
        self.assertEqual(len(self.match_requests),1)

    def test_category_handoff_and_navigation(self):
        self.page.goto(self.base)
        self.page.get_by_role('link',name='Фотограф',exact=True).click()
        expect(self.page).to_have_url(re.compile(r'/selection\?category='))
        expect(self.page.get_by_role('button',name='Подобрать людей',exact=True)).to_be_enabled()
        expect(self.page.get_by_label('Кого ищем?').locator('option:checked')).to_have_text('Фотограф')
        expect(self.page.locator('#results-panel')).to_be_hidden()
        self.assertEqual(self.match_requests,[])
        self.page.get_by_role('link',name='Главная',exact=True).first.click()
        expect(self.page).to_have_url(self.base+'/')
        expect(self.page.locator('#order-form')).to_have_count(0)
        self.page.get_by_role('link',name='Подбор',exact=True).first.click()
        expect(self.page).to_have_url(self.base+'/selection')
        expect(self.page.get_by_role('button',name='Подобрать людей',exact=True)).to_be_enabled()
        expect(self.page.get_by_label('Кого ищем?').locator('option:checked')).to_have_text('Ведущий')
        self.assertEqual(self.match_requests,[])

    def test_repeat_order_and_details(self):
        self.submit()
        expect(self.page.get_by_role('article')).to_have_count(3)
        names=self.page.get_by_role('article').locator('h3').all_text_contents()
        self.submit()
        expect(self.page.get_by_role('article')).to_have_count(3)
        self.assertEqual(names,self.page.get_by_role('article').locator('h3').all_text_contents())
        self.page.get_by_role('article').first.locator('summary').click()
        expect(self.page.get_by_text('26 сентября — нет среди занятых дат в каталоге').first).to_be_visible()

    def test_empty_and_working_suggestion(self):
        self.page.get_by_label('Бюджет на подрядчика').fill('1');self.submit()
        expect(self.page.get_by_role('heading',name='Пока без точного совпадения')).to_be_visible()
        self.page.get_by_role('button',name='Бюджет 500 000').click()
        expect(self.page.get_by_role('article')).to_have_count(1)
        expect(self.page.get_by_label('Бюджет на подрядчика')).to_have_value(re.compile(r'500\s000'))

    def test_absent_category(self):
        self.page.get_by_label('Город',exact=True).select_option(label='Зарубежье')
        self.page.get_by_label('Кого ищем?').select_option(label='Флорист');self.submit()
        expect(self.page.get_by_role('heading',name='Пока нет в каталоге')).to_be_visible()
        expect(self.page.get_by_role('article')).to_have_count(0)

    def test_mobile_and_invalid_budget(self):
        self.page.set_viewport_size({'width':375,'height':812})
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),375)
        self.page.screenshot(path=str(self.output/(self.backend+'-selection-mobile.png')),full_page=True,animations='disabled')
        self.page.get_by_label('Бюджет на подрядчика').fill('abc')
        self.page.get_by_role('button',name='Подобрать людей',exact=True).click()
        expect(self.page.get_by_label('Бюджет на подрядчика')).to_have_attribute('aria-invalid','true')
        self.assertEqual(self.match_requests,[])
        self.page.get_by_label('Бюджет на подрядчика').fill('1000000')
        self.submit()
        expect(self.page.get_by_role('article')).to_have_count(3)
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),375)

    def test_editor_auth_and_readonly_csv(self):
        self.page.goto(self.base+'/admin')
        self.page.get_by_label('Ключ редактора').fill('wrong')
        self.page.get_by_role('button',name='Открыть каталог').click()
        expect(self.page.get_by_role('status')).to_contain_text('Требуется ключ')
        self.page.get_by_label('Ключ редактора').fill('e2e-local-editor')
        self.page.get_by_role('button',name='Открыть каталог').click()
        expect(self.page.get_by_role('button',name='Сохранить изменения')).to_be_disabled()
        expect(self.page.get_by_role('status')).to_contain_text('CSV доступен')


@skipUnless(os.getenv('POSTGRES_TEST_URL'), 'Set POSTGRES_TEST_URL for PostgreSQL browser tests')
class PostgresBrowserTests(BrowserTests):
    backend = 'postgres'

    def test_editor_auth_and_readonly_csv(self):
        self.page.goto(self.base+'/admin')
        self.page.get_by_label('Ключ редактора').fill('e2e-local-editor')
        self.page.get_by_role('button',name='Открыть каталог').click()
        self.page.get_by_role('button',name='Добавить профиль').click()
        for label,value in [('ID','E2E-NEW'),('Имя','Тестовый подрядчик'),('Город','E2E_CITY'),
                            ('Цена от, ₸','100000'),('Категории — через |','Ведущий'),
                            ('Форматы — через |','корпоратив'),('Языки — через |','русский')]:
            self.page.get_by_label(label,exact=True).fill(value)
        self.page.get_by_role('button',name='Сохранить изменения').click()
        expect(self.page.get_by_role('status')).to_contain_text('Сохранено')
        self.page.get_by_label('Имя',exact=True).fill('Обновлённый подрядчик')
        self.page.get_by_role('button',name='Сохранить изменения').click()
        expect(self.page.get_by_role('heading',name='Обновлённый подрядчик',exact=True)).to_be_visible()
        self.page.get_by_role('button',name='Перечитать каталог').click()
        expect(self.page.get_by_label('Имя',exact=True)).to_have_value('Обновлённый подрядчик')
