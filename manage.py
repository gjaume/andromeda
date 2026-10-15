#!/usr/bin/env python
import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    from django.core.management import execute_from_command_line
    from django.core.management.commands.runserver import Command as Runserver

    Runserver.default_port = "8080"  # `runserver` sin puerto escucha en el 8080
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
