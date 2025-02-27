#
# Copyright (C) 2018  Red Hat, Inc.
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# the GNU General Public License v.2, or (at your option) any later version.
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY expressed or implied, including the implied warranties of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
# Public License for more details.  You should have received a copy of the
# GNU General Public License along with this program; if not, write to the
# Free Software Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.  Any Red Hat trademarks that are incorporated in the
# source code or documentation are not subject to the GNU General Public
# License and may only be used or replicated with the express permission of
# Red Hat, Inc.
#
# Red Hat Author(s): Vendula Poncova <vponcova@redhat.com>
#
import os
import tempfile
import unittest
from textwrap import dedent
from unittest.mock import patch

from blivet.size import Size

from pyanaconda.core.configuration.anaconda import AnacondaConfiguration
from pyanaconda.core.configuration.base import create_parser, read_config, write_config, \
    get_option, set_option, ConfigurationError, ConfigurationDataError, ConfigurationFileError, \
    Configuration
from pyanaconda.core.configuration.storage import StorageSection
from pyanaconda.core.configuration.ui import UserInterfaceSection
from pyanaconda.core.util import get_os_release_value
from pyanaconda.modules.common.constants import services
from pyanaconda.core.constants import SOURCE_TYPE_CLOSEST_MIRROR

# Path to the configuration directory of the repo.
CONFIG_DIR = os.environ.get("ANACONDA_DATA")


class ConfigurationTestCase(unittest.TestCase):
    """Test the configuration support."""

    @property
    def _content(self):
        return dedent("""

        [Main]
        string = Hello
        integer = 1
        boolean = False

        """)

    def _read_content(self, parser):

        with tempfile.NamedTemporaryFile("w") as f:
            # Prepare the config file.
            f.write(self._content)
            f.flush()

            # Read the config file.
            read_config(parser, f.name)

        return parser

    def test_read(self):
        parser = create_parser()
        self._read_content(parser)

    def test_invalid_read(self):
        parser = create_parser()

        with self.assertRaises(ConfigurationFileError) as cm:
            read_config(parser, "nonexistent/path/to/file")

        self.assertEqual(cm.exception._filename, "nonexistent/path/to/file")

    def test_write(self):
        parser = create_parser()
        self._read_content(parser)

        with tempfile.NamedTemporaryFile("r+") as f:
            # Write the config file.
            write_config(parser, f.name)
            f.flush()

            # Check the config file.
            self.assertEqual(f.read().strip(), self._content.strip())

    def test_invalid_write(self):
        parser = create_parser()

        with self.assertRaises(ConfigurationFileError) as cm:
            write_config(parser, "nonexistent/path/to/file")

        self.assertEqual(cm.exception._filename, "nonexistent/path/to/file")
        self.assertTrue(str(cm.exception).startswith(
            "The following error has occurred while handling the configuration file"
        ))

    def test_get(self):
        parser = create_parser()
        self._read_content(parser)

        self.assertEqual(get_option(parser, "Main", "string"), "Hello")
        self.assertEqual(get_option(parser, "Main", "integer"), "1")
        self.assertEqual(get_option(parser, "Main", "boolean"), "False")

        self.assertEqual(get_option(parser, "Main", "string", str), "Hello")
        self.assertEqual(get_option(parser, "Main", "integer", int), 1)
        self.assertEqual(get_option(parser, "Main", "boolean", bool), False)

    def test_invalid_get(self):
        parser = create_parser()
        self._read_content(parser)

        # Invalid value.
        with self.assertRaises(ConfigurationDataError) as cm:
            get_option(parser, "Main", "string", bool)

        self.assertEqual(cm.exception._section, "Main")
        self.assertEqual(cm.exception._option, "string")

        # Invalid option.
        with self.assertRaises(ConfigurationDataError) as cm:
            get_option(parser, "Main", "unknown")

        self.assertEqual(cm.exception._section, "Main")
        self.assertEqual(cm.exception._option, "unknown")

        # Invalid section.
        with self.assertRaises(ConfigurationDataError) as cm:
            get_option(parser, "Unknown", "unknown")

        self.assertEqual(cm.exception._section, "Unknown")
        self.assertEqual(cm.exception._option, "unknown")

    def test_set(self):
        parser = create_parser()
        self._read_content(parser)

        set_option(parser, "Main", "string", "Hi")
        set_option(parser, "Main", "integer", 2)
        set_option(parser, "Main", "boolean", True)

        self.assertEqual(get_option(parser, "Main", "string"), "Hi")
        self.assertEqual(get_option(parser, "Main", "integer"), "2")
        self.assertEqual(get_option(parser, "Main", "boolean"), "True")

        self.assertEqual(get_option(parser, "Main", "string", str), "Hi")
        self.assertEqual(get_option(parser, "Main", "integer", int), 2)
        self.assertEqual(get_option(parser, "Main", "boolean", bool), True)

    def test_invalid_set(self):
        parser = create_parser()
        self._read_content(parser)

        # Invalid option.
        with self.assertRaises(ConfigurationDataError) as cm:
            set_option(parser, "Main", "unknown", "value")

        self.assertEqual(cm.exception._section, "Main")
        self.assertEqual(cm.exception._option, "unknown")

        # Invalid section.
        with self.assertRaises(ConfigurationDataError) as cm:
            set_option(parser, "Unknown", "unknown", "value")

        self.assertEqual(cm.exception._section, "Unknown")
        self.assertEqual(cm.exception._option, "unknown")

        self.assertTrue(str(cm.exception).startswith(
            "The following error has occurred while handling the option"
        ))

    def test_configuration(self):
        config = Configuration()

        with tempfile.TemporaryDirectory() as directory:

            for filename in ["d.conf", "a.conf", "c", "b.conf"]:
                with open(os.path.join(directory, filename), mode="w") as f:
                    f.write("")

            config.read_from_directory(directory)

            self.assertEqual(
                [os.path.relpath(path, directory) for path in config.get_sources()],
                ["a.conf", "b.conf", "d.conf"]
            )


class AnacondaConfigurationTestCase(unittest.TestCase):
    """Test the Anaconda configuration."""

    def test_default_configuration(self):
        # Make sure that we are able to import conf.
        from pyanaconda.core.configuration.anaconda import conf
        self.assertEqual(conf.anaconda.debug, False)

    def test_source(self):
        conf = AnacondaConfiguration()
        sources = conf.get_sources()
        self.assertEqual(sources, [])

    def test_default_source(self):
        conf = AnacondaConfiguration.from_defaults()
        sources = conf.get_sources()
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0], os.environ.get("ANACONDA_CONFIG_TMP"))

    def test_default_validation(self):
        conf = AnacondaConfiguration.from_defaults()
        conf.validate()

        # Set invalid value.
        parser = conf.get_parser()
        parser["Anaconda"]["debug"] = "string"
        with self.assertRaises(ConfigurationError):
            conf.validate()

        # Remove a required option.
        parser.remove_option("Anaconda", "debug")
        with self.assertRaises(ConfigurationError):
            conf.validate()

        # Remove a required section.
        parser.remove_section("Anaconda")
        with self.assertRaises(ConfigurationError):
            conf.validate()

    def test_read(self):
        conf = AnacondaConfiguration()

        with tempfile.NamedTemporaryFile("w") as f:
            conf.read(f.name)
            self.assertEqual(len(conf.get_sources()), 1)
            self.assertEqual(conf.get_sources()[0], f.name)

    def test_default_read(self):
        AnacondaConfiguration.from_defaults()

    def test_write(self):
        conf = AnacondaConfiguration()

        with tempfile.NamedTemporaryFile("r+") as f:
            conf.write(f.name)
            f.flush()
            self.assertFalse(f.read(), "The file should be empty.")

    def test_default_write(self):
        conf = AnacondaConfiguration.from_defaults()

        with tempfile.NamedTemporaryFile("r+") as f:
            conf.write(f.name)
            f.flush()
            self.assertTrue(f.read(), "The file shouldn't be empty.")

    def test_set_from_files(self):
        conf = AnacondaConfiguration.from_defaults()
        paths = []

        with tempfile.TemporaryDirectory() as d:
            # Add nonexistent file.
            nonexistent = os.path.join(d, "nonexistent")
            paths.append(nonexistent)

            # Add empty directory.
            empty_dir = os.path.join(d, "empty")
            os.mkdir(empty_dir)
            paths.append(empty_dir)

            # Add existing file.
            existing = os.path.join(d, "a.conf")
            paths.append(existing)

            with open(existing, mode="w") as f:
                f.write("")

            # Add non-empty directory.
            conf_dir = os.path.join(d, "conf.d")
            os.mkdir(conf_dir)
            paths.append(conf_dir)

            for name in ["b.conf", "c.conf", "d"]:
                with open(os.path.join(conf_dir, name), mode="w") as f:
                    f.write("")

            # Check the paths.
            self.assertEqual(
                [os.path.relpath(path, d) for path in paths],
                ["nonexistent", "empty", "a.conf", "conf.d"]
            )

            conf._sources = []
            conf.set_from_files(paths)

            # Check the loaded files.
            self.assertEqual(
                [os.path.relpath(path, d) for path in conf.get_sources()],
                ["a.conf", "conf.d/b.conf", "conf.d/c.conf"]
            )

    def _check_configuration_sources(self, conf, file_names):
        """Check the loaded configuration sources."""
        file_paths = [os.path.join(CONFIG_DIR, path) for path in file_names]
        self.assertEqual(file_paths, conf.get_sources())

    @patch("pyanaconda.core.configuration.anaconda.ANACONDA_CONFIG_DIR", CONFIG_DIR)
    def test_set_from_no_product(self):
        conf = AnacondaConfiguration.from_defaults()

        with self.assertLogs(level="WARNING") as cm:
            conf.set_from_product()

        expected = \
            "Unable to find any suitable configuration files for the detected " \
            "product and variant names. No product configuration will be used."

        self.assertIn(expected, "\n".join(cm.output))

    @patch("pyanaconda.core.configuration.anaconda.ANACONDA_CONFIG_DIR", CONFIG_DIR)
    def test_set_from_requested_product(self):
        conf = AnacondaConfiguration.from_defaults()

        # Test an unknown requested product.
        with self.assertRaises(ConfigurationError) as cm:
            conf.set_from_product(
                requested_product="Unknown product",
                requested_variant="Unknown variant",
            )

        expected = "Unable to find any suitable configuration files " \
                   "for the product name 'Unknown product' and the " \
                   "variant name 'Unknown variant'."

        self.assertEqual(str(cm.exception), expected)

        # Test a known requested product.
        conf.set_from_product(
            requested_product="Fedora",
            requested_variant="Workstation",
        )

        self._check_configuration_sources(conf, [
            "anaconda.conf",
            "product.d/fedora.conf",
            "product.d/fedora-workstation.conf"
        ])

    @patch("pyanaconda.core.configuration.anaconda.ANACONDA_CONFIG_DIR", CONFIG_DIR)
    def test_set_from_buildstamp_product(self):
        conf = AnacondaConfiguration.from_defaults()

        # Test an unknown .buildstamp product.
        with self.assertLogs(level="WARNING") as cm:
            conf.set_from_product(
                buildstamp_product="Unknown product",
                buildstamp_variant="Unknown variant",
            )

        expected = \
            "Unable to find any suitable configuration files for the detected " \
            "product and variant names. No product configuration will be used."

        self.assertIn(expected, "\n".join(cm.output))

        # Test a known .buildstamp product.
        conf.set_from_product(
            buildstamp_product="Fedora",
            buildstamp_variant="Workstation",
        )

        self._check_configuration_sources(conf, [
            "anaconda.conf",
            "product.d/fedora.conf",
            "product.d/fedora-workstation.conf"
        ])

    @patch("pyanaconda.core.configuration.anaconda.ANACONDA_CONFIG_DIR", CONFIG_DIR)
    def test_set_from_default_product(self):
        conf = AnacondaConfiguration.from_defaults()

        # Test an unknown default product.
        with self.assertLogs(level="WARNING") as cm:
            conf.set_from_product(
                default_product="Unknown product",
            )

        expected = \
            "Unable to find any suitable configuration files for the detected " \
            "product and variant names. No product configuration will be used."

        self.assertIn(expected, "\n".join(cm.output))

        # Test a known default product.
        conf.set_from_product(
            default_product="Fedora"
        )

        self._check_configuration_sources(conf, [
            "anaconda.conf",
            "product.d/fedora.conf"
        ])

    @patch("pyanaconda.core.configuration.anaconda.ANACONDA_CONFIG_DIR", CONFIG_DIR)
    def test_set_from_detected_product(self):
        conf = AnacondaConfiguration.from_defaults()
        conf.set_from_product(get_os_release_value("NAME"))

    def test_kickstart_modules(self):
        conf = AnacondaConfiguration.from_defaults()

        self.assertEqual(
            set(conf.anaconda.kickstart_modules),
            set(service.service_name for service in (
                services.TIMEZONE,
                services.NETWORK,
                services.LOCALIZATION,
                services.SECURITY,
                services.USERS,
                services.PAYLOADS,
                services.STORAGE,
                services.SERVICES
            ))
        )

    def test_bootloader(self):
        conf = AnacondaConfiguration.from_defaults()
        self.assertIn("selinux", conf.bootloader.preserved_arguments)

    def test_default_partitioning(self):
        conf = AnacondaConfiguration.from_defaults()
        self.assertEqual(conf.storage.default_partitioning, [
            {
                'name': '/',
                'min': Size("1024 MiB"),
                'max': Size("70 GiB"),
            }, {
                'name': '/home',
                'min': Size("500 MiB"),
                'free': Size("50 GiB"),
            }
        ])

    def test_convert_partitioning(self):
        convert_line = StorageSection._convert_partitioning_line

        self.assertEqual(convert_line("/ (min 1 GiB, max 2 GiB, free 20 GiB)"), {
            "name": "/",
            "min": Size("1 GiB"),
            "max": Size("2 GiB"),
            "free": Size("20 GiB")
        })

        self.assertEqual(convert_line("/home (size 1 GiB)"), {
            "name": "/home",
            "size": Size("1 GiB")
        })

        self.assertEqual(convert_line("swap"), {
            "name": "swap"
        })

        with self.assertRaises(ValueError):
            convert_line("")

        with self.assertRaises(ValueError):
            convert_line("(size 1 GiB)")

        with self.assertRaises(ValueError):
            convert_line("/home (size)")

        with self.assertRaises(ValueError):
            convert_line("/home (invalid 1 GiB)")

        with self.assertRaises(ValueError):
            convert_line("/home  (size 1 GiB, min 2 GiB)")

        with self.assertRaises(ValueError):
            convert_line("/home  (max 2 GiB)")

    def test_default_installation_source(self):
        conf = AnacondaConfiguration.from_defaults()
        self.assertEqual(conf.payload.default_source, SOURCE_TYPE_CLOSEST_MIRROR)

    def test_default_password_policies(self):
        conf = AnacondaConfiguration.from_defaults()
        self.assertEqual(conf.ui.password_policies, [
            {
                'name': 'root',
                "quality": 1,
                "length": 6,
            }, {
                'name': 'user',
                "quality": 1,
                "length": 6,
                "empty": True,
            }, {
                'name': 'luks',
                "quality": 1,
                "length": 6,
            },
        ])

    def test_convert_password_policy(self):
        convert_line = UserInterfaceSection._convert_policy_line

        self.assertEqual(convert_line("root (quality 100, length 10, empty, strict)"), {
            "name": "root",
            "quality": 100,
            "length": 10,
            "empty": True,
            "strict": True,
        })

        self.assertEqual(convert_line("luks (quality 100, length 10)"), {
            "name": "luks",
            "quality": 100,
            "length": 10,
        })

        with self.assertRaises(ValueError):
            convert_line("")

        with self.assertRaises(ValueError):
            convert_line("(empty)")

        with self.assertRaises(ValueError):
            convert_line("user (quality)")

        with self.assertRaises(ValueError):
            convert_line("user (invalid 100)")

        # Missing length.
        with self.assertRaises(ValueError):
            convert_line("user (quality 100)")

        # Missing quality.
        with self.assertRaises(ValueError):
            convert_line("user (length 10)")
