# -*- coding: utf-8 -*-
"""python manage.py run_req001_mvp — thin wrapper around the isolated toolkit."""
from __future__ import annotations

import sys
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "REQ-001 MVP 一键本地试跑（不经过用例管理后台，不以 Allure/Scrcpy 为路径）"

    def add_arguments(self, parser):
        parser.add_argument("--avd", default=None)
        parser.add_argument("--timeout", type=int, default=240)
        parser.add_argument("--max-steps", type=int, default=20)
        parser.add_argument("--output-dir", default=None)

    def handle(self, *args, **options):
        root = Path(settings.BASE_DIR)
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from tools.req001.run_mvp import main

        argv = []
        if options.get("avd"):
            argv.extend(["--avd", options["avd"]])
        if options.get("timeout") is not None:
            argv.extend(["--timeout", str(options["timeout"])])
        if options.get("max_steps") is not None:
            argv.extend(["--max-steps", str(options["max_steps"])])
        if options.get("output_dir"):
            argv.extend(["--output-dir", options["output_dir"]])
        raise SystemExit(main(argv))
