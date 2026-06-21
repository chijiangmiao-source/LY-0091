import falcon
import json
import os
from jinja2 import Environment, FileSystemLoader
from app.config import APP_PORT

template_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")
jinja_env = Environment(loader=FileSystemLoader(template_dir))


def render_template(template_name, context=None):
    if context is None:
        context = {}
    template = jinja_env.get_template(template_name)
    return template.render(**context)


class LoginPageResource:
    async def on_get(self, req, resp):
        resp.content_type = "text/html; charset=utf-8"
        resp.text = render_template("login.html")


class DashboardPageResource:
    async def on_get(self, req, resp):
        resp.content_type = "text/html; charset=utf-8"
        resp.text = render_template("dashboard.html")


class StoresPageResource:
    async def on_get(self, req, resp):
        resp.content_type = "text/html; charset=utf-8"
        resp.text = render_template("stores.html")


class FittingRoomsPageResource:
    async def on_get(self, req, resp):
        resp.content_type = "text/html; charset=utf-8"
        resp.text = render_template("fitting_rooms.html")


class QueuePageResource:
    async def on_get(self, req, resp):
        resp.content_type = "text/html; charset=utf-8"
        resp.text = render_template("queue.html")


class LostItemsPageResource:
    async def on_get(self, req, resp):
        resp.content_type = "text/html; charset=utf-8"
        resp.text = render_template("lost_items.html")


class StatsPageResource:
    async def on_get(self, req, resp):
        resp.content_type = "text/html; charset=utf-8"
        resp.text = render_template("stats.html")


class MemberPageResource:
    async def on_get(self, req, resp):
        resp.content_type = "text/html; charset=utf-8"
        resp.text = render_template("member.html")
