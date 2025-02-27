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
import unittest
import tempfile
import os
from unittest.mock import patch

from pyanaconda.core.configuration.target import TargetType
from pyanaconda.core.constants import PAYLOAD_TYPE_DNF, PAYLOAD_TYPE_RPM_OSTREE
from pykickstart.constants import SELINUX_ENFORCING, SELINUX_PERMISSIVE

from pyanaconda.modules.common.errors.installation import SecurityInstallationError
from pyanaconda.modules.common.constants.services import SECURITY
from pyanaconda.modules.common.structures.realm import RealmData
from dasbus.typing import get_variant, Str, List, Bool
from pyanaconda.modules.security.security import SecurityService
from pyanaconda.modules.security.security_interface import SecurityInterface
from pyanaconda.modules.security.constants import SELinuxMode
from pyanaconda.modules.security.installation import ConfigureSELinuxTask, \
    RealmDiscoverTask, RealmJoinTask, ConfigureFingerprintAuthTask, \
    ConfigureAuthselectTask, ConfigureAuthconfigTask, AUTHSELECT_TOOL_PATH, \
    AUTHCONFIG_TOOL_PATH, PAM_SO_64_PATH, PAM_SO_PATH, PreconfigureFIPSTask, ConfigureFIPSTask
from tests.unit_tests.pyanaconda_tests import patch_dbus_publish_object, check_kickstart_interface, \
    check_task_creation, check_task_creation_list, PropertiesChangedCallback, check_dbus_property
from pyanaconda.modules.common.structures.requirement import Requirement


class SecurityInterfaceTestCase(unittest.TestCase):
    """Test DBus interface for the Security module."""

    def setUp(self):
        """Set up the security module."""
        # Set up the security module.
        self.security_module = SecurityService()
        self.security_interface = SecurityInterface(self.security_module)

        # Connect to the properties changed signal.
        self.callback = PropertiesChangedCallback()
        self.security_interface.PropertiesChanged.connect(self.callback)

    def _check_dbus_property(self, *args, **kwargs):
        check_dbus_property(
            self,
            SECURITY,
            self.security_interface,
            *args, **kwargs
        )

    def test_kickstart_properties(self):
        """Test kickstart properties."""
        self.assertEqual(self.security_interface.KickstartCommands,
                         ["auth", "authconfig", "authselect", "selinux", "realm"])
        self.assertEqual(self.security_interface.KickstartSections, [])
        self.assertEqual(self.security_interface.KickstartAddons, [])
        self.callback.assert_not_called()

    def test_selinux_property(self):
        """Test the selinux property."""
        self._check_dbus_property(
            "SELinux",
            SELINUX_ENFORCING
        )

    def test_authselect_property(self):
        """Test the authselect property."""
        self._check_dbus_property(
            "Authselect",
            ["sssd", "with-mkhomedir"]
        )

    def test_authconfig_property(self):
        """Test the authconfig property."""
        self._check_dbus_property(
            "Authconfig",
            ["--passalgo=yescrypt", "--useshadow"]
        )

    def test_fingerprint_auth_enabled(self):
        """Test the fingerprint_auth_enabled property."""
        self._check_dbus_property(
            "FingerprintAuthEnabled",
            True
        )

    def test_realm_property(self):
        """Test the realm property."""
        realm = {
            "name": get_variant(Str, "domain.example.com"),
            "discover-options": get_variant(List[Str], ["--client-software=sssd"]),
            "join-options": get_variant(List[Str], ["--one-time-password=password"]),
            "discovered": get_variant(Bool, True),
            "required-packages": get_variant(List[Str], [])
        }
        self._check_dbus_property(
            "Realm",
            realm
        )

    def _test_kickstart(self, ks_in, ks_out):
        check_kickstart_interface(self, self.security_interface, ks_in, ks_out)

    def test_no_kickstart(self):
        """Test with no kickstart."""
        ks_in = None
        ks_out = ""
        self._test_kickstart(ks_in, ks_out)

    def test_kickstart_empty(self):
        """Test with empty string."""
        ks_in = ""
        ks_out = ""
        self._test_kickstart(ks_in, ks_out)

    def test_selinux_kickstart(self):
        """Test the selinux command."""
        ks_in = """
        selinux --permissive
        """
        ks_out = """
        # SELinux configuration
        selinux --permissive
        """
        self._test_kickstart(ks_in, ks_out)

    def test_auth_kickstart(self):
        """Test the auth command."""
        ks_in = """
        auth --passalgo=yescrypt --useshadow
        """
        ks_out = """
        # System authorization information
        auth --passalgo=yescrypt --useshadow
        """
        self._test_kickstart(ks_in, ks_out)

    def test_authconfig_kickstart(self):
        """Test the authconfig command."""
        ks_in = """
        authconfig --passalgo=yescrypt --useshadow
        """
        ks_out = """
        # System authorization information
        auth --passalgo=yescrypt --useshadow
        """
        self._test_kickstart(ks_in, ks_out)

    def test_authselect_kickstart(self):
        """Test the authselect command."""
        ks_in = """
        authselect select sssd with-mkhomedir
        """
        ks_out = """
        # System authorization information
        authselect select sssd with-mkhomedir
        """
        self._test_kickstart(ks_in, ks_out)

    def test_realm_kickstart(self):
        """Test the realm command."""
        ks_in = """
        realm join --one-time-password=password --client-software=sssd domain.example.com
        """
        ks_out = """
        # Realm or domain membership
        realm join --one-time-password=password --client-software=sssd domain.example.com
        """
        self._test_kickstart(ks_in, ks_out)

    @patch_dbus_publish_object
    def test_realm_discover_default(self, publisher):
        """Test module in default state with realm discover task."""
        realm_discover_task_path = self.security_interface.DiscoverRealmWithTask()
        obj = check_task_creation(self, realm_discover_task_path, publisher, RealmDiscoverTask)
        self.assertEqual(obj.implementation._realm_data.name, "")
        self.assertEqual(obj.implementation._realm_data.discover_options, [])

    @patch_dbus_publish_object
    def test_realm_discover_configured(self, publisher):
        """Test module in configured state with realm discover task."""
        realm = RealmData()
        realm.name = "domain.example.com"
        realm.discover_options = ["--client-software=sssd"]

        self.security_interface.SetRealm(RealmData.to_structure(realm))
        realm_discover_task_path = self.security_interface.DiscoverRealmWithTask()

        obj = check_task_creation(self, realm_discover_task_path, publisher, RealmDiscoverTask)
        self.assertEqual(obj.implementation._realm_data.name, "domain.example.com")
        self.assertEqual(obj.implementation._realm_data.discover_options, ["--client-software=sssd"])

    @patch_dbus_publish_object
    def test_install_with_tasks_default(self, publisher):
        """Test InstallWithTasks."""
        task_classes = [
            ConfigureSELinuxTask,
            ConfigureFingerprintAuthTask,
            ConfigureAuthselectTask,
            ConfigureAuthconfigTask,
        ]
        task_paths = self.security_interface.InstallWithTasks()
        task_objs = check_task_creation_list(self, task_paths, publisher, task_classes)

        # ConfigureSELinuxTask
        obj = task_objs[0]
        self.assertEqual(obj.implementation._selinux_mode, SELinuxMode.DEFAULT)
        # ConfigureFingerprintAuthTask
        obj = task_objs[1]
        self.assertEqual(obj.implementation._fingerprint_auth_enabled, False)
        # ConfigureAuthselectTask
        obj = task_objs[2]
        self.assertEqual(obj.implementation._authselect_options, [])
        # ConfigureAuthconfigTask
        obj = task_objs[3]
        self.assertEqual(obj.implementation._authconfig_options, [])

    @patch_dbus_publish_object
    def test_realm_join_default(self, publisher):
        """Test module in default state with realm join task."""
        realm_join_task_path = self.security_interface.JoinRealmWithTask()
        obj = check_task_creation(self, realm_join_task_path, publisher, RealmJoinTask)
        self.assertEqual(obj.implementation._realm_data.discovered, False)
        self.assertEqual(obj.implementation._realm_data.name, "")
        self.assertEqual(obj.implementation._realm_data.join_options, [])

    @patch_dbus_publish_object
    def test_install_with_tasks_configured(self, publisher):
        """Test install tasks - module in configured state."""
        realm = RealmData()
        realm.name = "domain.example.com"
        realm.discover_options = ["--client-software=sssd"]
        realm.join_options = ["--one-time-password=password"]
        realm.discovered = True

        authselect = ['select', 'sssd']
        authconfig = ['--passalgo=yescrypt', '--useshadow']
        fingerprint = True

        self.security_interface.SetRealm(RealmData.to_structure(realm))
        self.security_interface.SetSELinux(SELINUX_PERMISSIVE)
        self.security_interface.SetAuthselect(authselect)
        self.security_interface.SetAuthconfig(authconfig)
        self.security_interface.SetFingerprintAuthEnabled(fingerprint)

        task_classes = [
            ConfigureSELinuxTask,
            ConfigureFingerprintAuthTask,
            ConfigureAuthselectTask,
            ConfigureAuthconfigTask,
        ]
        task_paths = self.security_interface.InstallWithTasks()
        task_objs = check_task_creation_list(self, task_paths, publisher, task_classes)

        # ConfigureSELinuxTask
        obj = task_objs[0]
        self.assertEqual(obj.implementation._selinux_mode, SELinuxMode.PERMISSIVE)
        # ConfigureFingerprintAuthTask
        obj = task_objs[1]
        self.assertEqual(obj.implementation._fingerprint_auth_enabled, fingerprint)
        # ConfigureAuthselectTask
        obj = task_objs[2]
        self.assertEqual(obj.implementation._authselect_options, authselect)
        # ConfigureAuthconfigTask
        obj = task_objs[3]
        self.assertEqual(obj.implementation._authconfig_options, authconfig)

    @patch_dbus_publish_object
    def test_realm_join_configured(self, publisher):
        """Test module in configured state with realm join task."""
        realm = RealmData()
        realm.name = "domain.example.com"
        realm.discover_options = ["--client-software=sssd"]
        realm.join_options = ["--one-time-password=password"]
        realm.discovered = True

        self.security_interface.SetRealm(RealmData.to_structure(realm))
        realm_join_task_path = self.security_interface.JoinRealmWithTask()

        obj = check_task_creation(self, realm_join_task_path, publisher, RealmJoinTask)
        self.assertEqual(obj.implementation._realm_data.discovered, True)
        self.assertEqual(obj.implementation._realm_data.name, "domain.example.com")
        self.assertEqual(obj.implementation._realm_data.join_options, ["--one-time-password=password"])

    @patch_dbus_publish_object
    def test_realm_data_propagation(self, publisher):
        """Test that realm data changes propagate to realm join task."""
        # We connect to the realm_changed signal and update the realm data holder
        # in the realm join task when the signal is triggered.
        realm1 = RealmData()
        realm1.name = "domain.example.com"
        realm1.discover_options = ["--client-software=sssd"]
        realm1.discovered = False

        self.security_interface.SetRealm(RealmData.to_structure(realm1))
        realm_join_task_path = self.security_interface.JoinRealmWithTask()

        # realm join - after task creation
        obj = check_task_creation(self, realm_join_task_path, publisher, RealmJoinTask)
        self.assertEqual(obj.implementation._realm_data.discovered, False)
        self.assertEqual(obj.implementation._realm_data.name, "domain.example.com")
        self.assertEqual(obj.implementation._realm_data.join_options, [])

        # change realm data and check the changes propagate to the realm join task
        realm2 = RealmData()
        realm2.name = "domain.example.com"
        realm2.discover_options = ["--client-software=sssd"]
        realm2.join_options = ["--one-time-password=password"]
        realm2.discovered = True

        self.security_interface.SetRealm(RealmData.to_structure(realm2))

        # realm join - after realm data update
        self.assertEqual(obj.implementation._realm_data.discovered, True)
        self.assertEqual(obj.implementation._realm_data.name, "domain.example.com")
        self.assertEqual(obj.implementation._realm_data.join_options, ["--one-time-password=password"])

    @patch_dbus_publish_object
    def test_preconfigure_fips_with_task(self, publisher):
        """Test the PreconfigureFIPSWithTask method."""
        task_path = self.security_interface.PreconfigureFIPSWithTask(PAYLOAD_TYPE_DNF)
        obj = check_task_creation(self, task_path, publisher, PreconfigureFIPSTask)
        self.assertEqual(obj.implementation._sysroot, "/mnt/sysroot")
        self.assertEqual(obj.implementation._payload_type, PAYLOAD_TYPE_DNF)
        self.assertEqual(obj.implementation._fips_enabled, False)

    @patch_dbus_publish_object
    def test_configure_fips_with_task(self, publisher):
        """Test the ConfigureFIPSWithTask method."""
        task_path = self.security_interface.ConfigureFIPSWithTask()
        obj = check_task_creation(self, task_path, publisher, ConfigureFIPSTask)
        self.assertEqual(obj.implementation._sysroot, "/mnt/sysroot")
        self.assertEqual(obj.implementation._fips_enabled, False)

    def test_collect_requirements_default(self):
        """Test requrements are empty by default."""
        reqs = self.security_interface.CollectRequirements()
        self.assertListEqual(reqs, [])

    @patch("pyanaconda.modules.security.security.kernel_arguments")
    def test_fips_requirements(self, kernel_arguments_mock):
        """Test the package requirements for fips."""
        kernel_arguments_mock.is_enabled.return_value = True
        self.assertEqual(self.security_interface.CollectRequirements(), [
            {
                "type": get_variant(Str, "package"),
                "name": get_variant(Str, "/usr/bin/fips-mode-setup"),
                "reason": get_variant(Str, "Required for FIPS compliance.")
            }
        ])
        kernel_arguments_mock.is_enabled.assert_called_once_with("fips")

    def test_realmd_requirements(self):
        """Test that package requirements in realm data propagate correctly."""
        realm = RealmData()
        realm.name = "domain.example.com"
        realm.discover_options = ["--client-software=sssd"]
        realm.join_options = ["--one-time-password=password"]
        realm.discovered = True
        realm.required_packages = ["realmd", "foo", "bar"]

        self.security_interface.SetRealm(RealmData.to_structure(realm))

        # check that the teamd package is requested
        self.assertEqual(self.security_interface.CollectRequirements(), [
            {
                "type": get_variant(Str, "package"),
                "name": get_variant(Str, "realmd"),
                "reason": get_variant(Str, "Needed to join a realm.")
            },
            {
                "type": get_variant(Str, "package"),
                "name": get_variant(Str, "foo"),
                "reason": get_variant(Str, "Needed to join a realm.")
            },
            {
                "type": get_variant(Str, "package"),
                "name": get_variant(Str, "bar"),
                "reason": get_variant(Str, "Needed to join a realm.")
            }
        ])

    def test_authselect_requirements(self):
        """Test that package requirements for authselect propagate correctly."""

        self.security_interface.SetAuthconfig(['--passalgo=yescrypt', '--useshadow'])
        requirements = Requirement.from_structure_list(
            self.security_interface.CollectRequirements()
        )
        self.assertEqual(len(requirements), 1)
        self.assertEqual(requirements[0].type, "package")
        self.assertEqual(requirements[0].name, "authselect-compat")

        self.security_interface.SetAuthconfig([])
        self.security_interface.SetAuthselect(['select', 'sssd'])
        requirements = Requirement.from_structure_list(
            self.security_interface.CollectRequirements()
        )
        self.assertEqual(len(requirements), 1)
        self.assertEqual(requirements[0].type, "package")
        self.assertEqual(requirements[0].name, "authselect")

        self.security_interface.SetAuthconfig([])
        self.security_interface.SetAuthselect([])
        self.security_interface.SetFingerprintAuthEnabled(True)
        requirements = Requirement.from_structure_list(
            self.security_interface.CollectRequirements()
        )
        self.assertEqual(len(requirements), 1)
        self.assertEqual(requirements[0].type, "package")
        self.assertEqual(requirements[0].name, "authselect")


class SecurityTasksTestCase(unittest.TestCase):
    """Test the secusrity tasks."""

    def setUp(self):
        """Set up the security module."""
        self.security_module = SecurityService()
        self.security_interface = SecurityInterface(self.security_module)

        # Connect to the properties changed signal.
        self.callback = PropertiesChangedCallback()
        self.security_interface.PropertiesChanged.connect(self.callback)

    def test_configure_selinux_task_disable(self):
        """Test SELinux configuration task - SELinux disabled."""
        content = """
        SELINUX=disabled
        """

        with tempfile.TemporaryDirectory() as sysroot:
            os.makedirs(os.path.join(sysroot, "etc/selinux/"))
            os.mknod(os.path.join(sysroot, "etc/selinux/config"))

            ConfigureSELinuxTask(
                sysroot=sysroot,
                selinux_mode=SELinuxMode.DISABLED
            ).run()

            with open(os.path.join(sysroot, "etc/selinux/config")) as f:
                self.assertEqual(f.read().strip(), content.strip())

    def test_configure_selinux_task_enforcing(self):
        """Test SELinux configuration task - SELinux enforcing."""
        content = """
        SELINUX=enforcing
        """

        with tempfile.TemporaryDirectory() as sysroot:
            os.makedirs(os.path.join(sysroot, "etc/selinux/"))
            os.mknod(os.path.join(sysroot, "etc/selinux/config"))

            ConfigureSELinuxTask(
                sysroot=sysroot,
                selinux_mode=SELinuxMode.ENFORCING
            ).run()

            with open(os.path.join(sysroot, "etc/selinux/config")) as f:
                self.assertEqual(f.read().strip(), content.strip())

    def test_configure_selinux_task_permissive(self):
        """Test SELinux configuration task - SELinux permissive."""
        content = """
        SELINUX=permissive
        """

        with tempfile.TemporaryDirectory() as sysroot:
            os.makedirs(os.path.join(sysroot, "etc/selinux/"))
            os.mknod(os.path.join(sysroot, "etc/selinux/config"))

            ConfigureSELinuxTask(
                sysroot=sysroot,
                selinux_mode=SELinuxMode.PERMISSIVE
            ).run()

            with open(os.path.join(sysroot, "etc/selinux/config")) as f:
                self.assertEqual(f.read().strip(), content.strip())

    def test_configure_selinux_task_default(self):
        """Test SELinux configuration task - SELinux default."""
        content = """
        SELINUX=foo
        """

        with tempfile.TemporaryDirectory() as sysroot:
            os.makedirs(os.path.join(sysroot, "etc/selinux/"))
            with open(os.path.join(sysroot, "etc/selinux/config"), "wt") as f:
                f.write(content)
                f.close()

            # check the default value in the SELinux config file is not changed
            ConfigureSELinuxTask(
                sysroot=sysroot,
                selinux_mode=SELinuxMode.DEFAULT
            ).run()

            with open(os.path.join(sysroot, "etc/selinux/config")) as f:
                self.assertEqual(f.read().strip(), content.strip())

    @patch('pyanaconda.core.util.execWithCapture')
    def test_realm_discover_success_task(self, execWithCapture):
        """Test the realm discover setup task - success."""
        execWithCapture.return_value = """foo-domain-discovered
                                          required-package:package-foo
                                          required-package:package-bar
                                          required-package:package-baz"""

        with tempfile.TemporaryDirectory() as sysroot:
            os.makedirs(os.path.join(sysroot, "usr/bin"))
            os.mknod(os.path.join(sysroot, "usr/bin/realm"))
            self.assertTrue(os.path.exists(os.path.join(sysroot, "usr/bin/realm")))

            realm_data = RealmData()
            realm_data.name = "foo-domain"
            realm_data.discover_options = ["--bar", "baz"]

            task = RealmDiscoverTask(sysroot=sysroot, realm_data=realm_data)
            new_realm_data = task.run()

            # check if the realm command invocation looks right
            execWithCapture.assert_called_once_with('realm',
                                                  ['discover', '--verbose', '--bar', 'baz', 'foo-domain'],
                                                  filter_stderr=True)

            # check if the results returned by the task look correct
            self.assertTrue(new_realm_data.discovered)
            self.assertListEqual(new_realm_data.required_packages, ["realmd", "package-foo", "package-bar", "package-baz"])

    @patch('pyanaconda.core.util.execWithCapture')
    def test_realm_discover_success_with_garbage_task(self, execWithCapture):
        """Test the realm discover setup task - success with garbage in output."""
        execWithCapture.return_value = """foo-domain-discovered
                                          stuff-foo
                                          required-package:package-foo
                                          required-package:package-bar


                                          required-package:package-baz
                                          required-package:
                                          unrelatedstuff"""

        with tempfile.TemporaryDirectory() as sysroot:
            os.makedirs(os.path.join(sysroot, "usr/bin"))
            os.mknod(os.path.join(sysroot, "usr/bin/realm"))
            self.assertTrue(os.path.exists(os.path.join(sysroot, "usr/bin/realm")))

            realm_data = RealmData()
            realm_data.name = "foo-domain"
            realm_data.discover_options = ["--bar", "baz"]

            task = RealmDiscoverTask(sysroot=sysroot, realm_data=realm_data)
            new_realm_data = task.run()

            # check if the realm command invocation looks right
            execWithCapture.assert_called_once_with('realm',
                                                  ['discover', '--verbose', '--bar', 'baz', 'foo-domain'],
                                                  filter_stderr=True)

            # check if the results returned by the task look correct
            self.assertTrue(new_realm_data.discovered)
            self.assertListEqual(new_realm_data.required_packages, ["realmd", "package-foo", "package-bar", "package-baz"])

    @patch('pyanaconda.core.util.execWithCapture')
    def test_realm_discover_success_no_extra_packages_with_garbage_task(self, execWithCapture):
        """Test the realm discover setup task - success, no extra packages, garbage in output."""
        execWithCapture.return_value = """foo-domain-discovered
                                       stuff, stuff
                                       stuff
                                       dsdsd dadasd
                                       """

        with tempfile.TemporaryDirectory() as sysroot:
            os.makedirs(os.path.join(sysroot, "usr/bin"))
            os.mknod(os.path.join(sysroot, "usr/bin/realm"))
            self.assertTrue(os.path.exists(os.path.join(sysroot, "usr/bin/realm")))

            realm_data = RealmData()
            realm_data.name = "foo-domain"
            realm_data.discover_options = ["--bar", "baz"]

            task = RealmDiscoverTask(sysroot=sysroot, realm_data=realm_data)
            new_realm_data = task.run()

            # check if the realm command invocation looks right
            execWithCapture.assert_called_once_with('realm',
                                                  ['discover', '--verbose', '--bar', 'baz', 'foo-domain'],
                                                  filter_stderr=True)

            # check if the results returned by the task look correct
            self.assertTrue(new_realm_data.discovered)
            self.assertListEqual(new_realm_data.required_packages, ["realmd"])

    @patch('pyanaconda.core.util.execWithCapture')
    def test_realm_discover_failure(self, execWithCapture):
        """Test the realm discover setup task - discovery failed."""
        execWithCapture.return_value = ""

        with tempfile.TemporaryDirectory() as sysroot:
            os.makedirs(os.path.join(sysroot, "usr/bin"))
            os.mknod(os.path.join(sysroot, "usr/bin/realm"))
            self.assertTrue(os.path.exists(os.path.join(sysroot, "usr/bin/realm")))

            realm_data = RealmData()
            realm_data.name = "foo-domain"
            realm_data.discover_options = ["--bar", "baz"]

            task = RealmDiscoverTask(sysroot=sysroot, realm_data=realm_data)
            new_realm_data = task.run()

            # check if the realm command invocation looks right
            execWithCapture.assert_called_once_with('realm',
                                                  ['discover', '--verbose', '--bar', 'baz', 'foo-domain'],
                                                  filter_stderr=True)

            # check if the results returned by the task look correct
            self.assertFalse(new_realm_data.discovered)
            # if realm discover invocation fails to discover a realm, we still add realmd as a required package
            self.assertListEqual(new_realm_data.required_packages, ["realmd"])

    @patch('pyanaconda.core.util.execWithCapture')
    def test_realm_discover_failure_with_exception(self, execWithCapture):
        """Test the realm discover setup task - discovery failed with exception."""
        execWithCapture.return_value = ""
        execWithCapture.side_effect = OSError()

        with tempfile.TemporaryDirectory() as sysroot:
            os.makedirs(os.path.join(sysroot, "usr/bin"))
            os.mknod(os.path.join(sysroot, "usr/bin/realm"))
            self.assertTrue(os.path.exists(os.path.join(sysroot, "usr/bin/realm")))

            realm_data = RealmData()
            realm_data.name = "foo-domain"
            realm_data.discover_options = ["--bar", "baz"]

            task = RealmDiscoverTask(sysroot=sysroot, realm_data=realm_data)
            new_realm_data = task.run()

            # check if the realm command invocation looks right
            execWithCapture.assert_called_once_with('realm',
                                                  ['discover', '--verbose', '--bar', 'baz', 'foo-domain'],
                                                  filter_stderr=True)

            # check if the results returned by the task look correct
            self.assertFalse(new_realm_data.discovered)
            # if realm discover invocation fails hard, we don't add realmd as a required package
            self.assertListEqual(new_realm_data.required_packages, [])

    @patch('pyanaconda.core.util.execWithCapture')
    def test_realm_discover_no_realm_name(self, execWithCapture):
        """Test the realm discover setup task - no realm name."""
        with tempfile.TemporaryDirectory() as sysroot:
            os.makedirs(os.path.join(sysroot, "usr/bin"))
            os.mknod(os.path.join(sysroot, "usr/bin/realm"))
            self.assertTrue(os.path.exists(os.path.join(sysroot, "usr/bin/realm")))

            realm_data = RealmData()
            realm_data.name = ""
            realm_data.discover_options = []

            task = RealmDiscoverTask(sysroot=sysroot, realm_data=realm_data)
            new_realm_data = task.run()

            # check if the realm command invocation looks right
            execWithCapture.assert_not_called()

            # no realm name so it can not be discovered
            self.assertFalse(new_realm_data.discovered)
            # if realm can't be discovered, we can't join it so no extra packages are needed
            self.assertListEqual(new_realm_data.required_packages, [])

    @patch('pyanaconda.core.util.execWithRedirect')
    def test_realm_join(self, execWithRedirect):
        """Test the realm join install task."""
        with tempfile.TemporaryDirectory() as sysroot:
            os.makedirs(os.path.join(sysroot, "usr/bin"))
            os.mknod(os.path.join(sysroot, "usr/bin/realm"))
            self.assertTrue(os.path.exists(os.path.join(sysroot, "usr/bin/realm")))

            realm_data = RealmData()
            realm_data.name = "foo-realm"
            realm_data.join_options = ["--bar", "baz"]
            realm_data.discovered = True
            task = RealmJoinTask(sysroot=sysroot, realm_data=realm_data)
            task.run()

            # check if the realm command invocation looks right
            execWithRedirect.assert_called_once_with('realm',
                                                     ['join', '--install', sysroot, '--verbose',
                                                      '--no-password', '--bar', 'baz'])

    @patch('pyanaconda.core.util.execWithRedirect')
    def test_realm_join_one_time_password(self, execWithRedirect):
        """Test the realm join install task - one time password."""
        with tempfile.TemporaryDirectory() as sysroot:
            os.makedirs(os.path.join(sysroot, "usr/bin"))
            os.mknod(os.path.join(sysroot, "usr/bin/realm"))
            self.assertTrue(os.path.exists(os.path.join(sysroot, "usr/bin/realm")))

            realm_data = RealmData()
            realm_data.name = "foo-realm"
            realm_data.join_options=["--one-time-password", "abcdefgh"]
            realm_data.discovered = True

            task = RealmJoinTask(sysroot=sysroot, realm_data=realm_data)
            task.run()

            # check if the realm command invocation looks right
            execWithRedirect.assert_called_once_with('realm',
                                                     ['join', '--install', sysroot, '--verbose',
                                                      '--one-time-password', 'abcdefgh'])

    @patch('pyanaconda.core.util.execWithRedirect')
    def test_realm_join_non_zero_return_value(self, execWithRedirect):
        """Test the realm join install task - non zero return value."""
        execWithRedirect.return_value = 1

        with tempfile.TemporaryDirectory() as sysroot:
            os.makedirs(os.path.join(sysroot, "usr/bin"))
            os.mknod(os.path.join(sysroot, "usr/bin/realm"))
            self.assertTrue(os.path.exists(os.path.join(sysroot, "usr/bin/realm")))

            realm_data = RealmData()
            realm_data.name = "foo-realm"
            realm_data.join_options = ["--one-time-password", "abcdefgh"]
            realm_data.discovered = True

            task = RealmJoinTask(sysroot=sysroot, realm_data=realm_data)
            task.run()

            # check if the realm command invocation looks right
            execWithRedirect.assert_called_once_with('realm',
                                                     ['join', '--install', sysroot, '--verbose',
                                                      '--one-time-password', 'abcdefgh'])

    @patch('pyanaconda.core.util.execWithRedirect')
    def test_realm_join_exception(self, execWithRedirect):
        """Test the realm join install task - exception."""
        execWithRedirect.side_effect = OSError()

        with tempfile.TemporaryDirectory() as sysroot:
            os.makedirs(os.path.join(sysroot, "usr/bin"))
            os.mknod(os.path.join(sysroot, "usr/bin/realm"))
            self.assertTrue(os.path.exists(os.path.join(sysroot, "usr/bin/realm")))

            realm_data = RealmData()
            realm_data.name = "foo-realm"
            realm_data.join_options = ["--one-time-password", "abcdefgh"]
            realm_data.discovered = True

            task = RealmJoinTask(sysroot=sysroot, realm_data=realm_data)
            task.run()

            # check if the realm command invocation looks right
            execWithRedirect.assert_called_once_with('realm',
                                                     ['join', '--install', sysroot, '--verbose',
                                                      '--one-time-password', 'abcdefgh'])

    @patch('pyanaconda.core.util.execWithRedirect')
    def test_realm_join_not_discovered(self, execWithRedirect):
        """Test the realm join install task - no realm discovered."""
        with tempfile.TemporaryDirectory() as sysroot:
            os.makedirs(os.path.join(sysroot, "usr/bin"))
            os.mknod(os.path.join(sysroot, "usr/bin/realm"))
            self.assertTrue(os.path.exists(os.path.join(sysroot, "usr/bin/realm")))

            realm_data = RealmData()
            realm_data.name = "foo-realm"
            realm_data.join_options = ["--bar", "baz"]
            realm_data.discovered = False

            task = RealmJoinTask(sysroot=sysroot, realm_data=realm_data)
            task.run()

            # check if the realm command invocation looks right
            execWithRedirect.assert_not_called()

    @patch('pyanaconda.core.util.execWithRedirect')
    def test_configure_fingerprint_auth_task(self, execWithRedirect):
        """Test the configure fingerprint task."""
        with tempfile.TemporaryDirectory() as sysroot:

            authselect_dir = os.path.normpath(sysroot + os.path.dirname(AUTHSELECT_TOOL_PATH))
            authselect_path = os.path.normpath(sysroot + AUTHSELECT_TOOL_PATH)
            pam_so_dir = os.path.normpath(sysroot + os.path.dirname(PAM_SO_PATH))
            pam_so_path = os.path.normpath(sysroot + PAM_SO_PATH)
            pam_so_64_dir = os.path.normpath(sysroot + os.path.dirname(PAM_SO_64_PATH))
            pam_so_64_path = os.path.normpath(sysroot + PAM_SO_64_PATH)

            os.makedirs(pam_so_dir)
            os.makedirs(pam_so_64_dir)
            os.makedirs(authselect_dir)

            # Pam library is missing
            task = ConfigureFingerprintAuthTask(
                sysroot=sysroot,
                fingerprint_auth_enabled=True
            )
            task.run()
            execWithRedirect.assert_not_called()

            # The authselect command is missing
            execWithRedirect.reset_mock()
            os.mknod(pam_so_path)
            task = ConfigureFingerprintAuthTask(
                sysroot=sysroot,
                fingerprint_auth_enabled=True
            )
            task.run()
            execWithRedirect.assert_not_called()
            os.remove(pam_so_path)

            # Authselect command and pam library are there
            execWithRedirect.reset_mock()
            os.mknod(pam_so_path)
            os.mknod(authselect_path)
            task = ConfigureFingerprintAuthTask(
                sysroot=sysroot,
                fingerprint_auth_enabled=True
            )
            task.run()
            execWithRedirect.assert_called_once_with(
                AUTHSELECT_TOOL_PATH,
                ["select", "sssd", "with-fingerprint", "with-silent-lastlog", "--force"],
                root=sysroot
            )
            os.remove(pam_so_path)
            os.remove(authselect_path)

            # Authselect command and pam library are there
            execWithRedirect.reset_mock()
            os.mknod(pam_so_64_path)
            os.mknod(authselect_path)
            task = ConfigureFingerprintAuthTask(
                sysroot=sysroot,
                fingerprint_auth_enabled=True
            )
            task.run()
            execWithRedirect.assert_called_once_with(
                AUTHSELECT_TOOL_PATH,
                ["select", "sssd", "with-fingerprint", "with-silent-lastlog", "--force"],
                root=sysroot
            )
            os.remove(pam_so_64_path)
            os.remove(authselect_path)

    @patch('pyanaconda.core.util.execWithRedirect')
    def test_configure_authselect_task(self, execWithRedirect):
        """Test the configure authselect task."""
        with tempfile.TemporaryDirectory() as sysroot:

            authselect_dir = os.path.normpath(sysroot + os.path.dirname(AUTHSELECT_TOOL_PATH))
            authselect_path = os.path.normpath(sysroot + AUTHSELECT_TOOL_PATH)
            os.makedirs(authselect_dir)

            # The authselect command is missing
            execWithRedirect.reset_mock()
            task = ConfigureAuthselectTask(
                sysroot=sysroot,
                authselect_options=["select", "sssd", "with-mkhomedir"]
            )
            with self.assertRaises(SecurityInstallationError):
                task.run()
            execWithRedirect.assert_not_called()

            # The authselect command is there
            execWithRedirect.reset_mock()
            os.mknod(authselect_path)
            task = ConfigureAuthselectTask(
                sysroot=sysroot,
                authselect_options=["select", "sssd", "with-mkhomedir"]
            )
            task.run()
            execWithRedirect.assert_called_once_with(
                AUTHSELECT_TOOL_PATH,
                ["select", "sssd", "with-mkhomedir", "--force"],
                root=sysroot
            )
            os.remove(authselect_path)

    @patch('pyanaconda.core.util.execWithRedirect')
    def test_configure_authconfig_task(self, execWithRedirect):
        """Test the configure authconfig task."""
        with tempfile.TemporaryDirectory() as sysroot:

            authconfig_dir = os.path.normpath(sysroot + os.path.dirname(AUTHCONFIG_TOOL_PATH))
            authconfig_path = os.path.normpath(sysroot + AUTHCONFIG_TOOL_PATH)
            os.makedirs(authconfig_dir)

            # The authconfig command is missing
            execWithRedirect.reset_mock()
            task = ConfigureAuthconfigTask(
                sysroot=sysroot,
                authconfig_options=["--passalgo=yescrypt", "--useshadow"]
            )
            with self.assertRaises(SecurityInstallationError):
                task.run()
            execWithRedirect.assert_not_called()

            # The authconfig command is there
            execWithRedirect.reset_mock()
            os.mknod(authconfig_path)
            task = ConfigureAuthconfigTask(
                sysroot=sysroot,
                authconfig_options=["--passalgo=yescrypt", "--useshadow"]
            )
            task.run()
            execWithRedirect.assert_called_once_with(
                AUTHCONFIG_TOOL_PATH,
                ["--update", "--nostart", "--passalgo=yescrypt", "--useshadow"],
                root=sysroot
            )
            os.remove(authconfig_path)

    def test_preconfigure_fips_task_disabled(self):
        """Test the PreconfigureFIPSTask task with disabled FIPS."""
        task = PreconfigureFIPSTask(
            sysroot="/mnt/sysroot",
            payload_type=PAYLOAD_TYPE_DNF,
            fips_enabled=False,
        )

        with self.assertLogs(level="DEBUG") as cm:
            task.run()

        msg = "FIPS is not enabled. Skipping."
        self.assertTrue(any(map(lambda x: msg in x, cm.output)))

    def test_preconfigure_fips_task_payload(self):
        """Test the PreconfigureFIPSTask task with a wrong payload."""
        task = PreconfigureFIPSTask(
            sysroot="/mnt/sysroot",
            payload_type=PAYLOAD_TYPE_RPM_OSTREE,
            fips_enabled=True,
        )

        with self.assertLogs(level="DEBUG") as cm:
            task.run()

        msg = "Don't set up FIPS for the RPM_OSTREE payload."
        self.assertTrue(any(map(lambda x: msg in x, cm.output)))

    def test_preconfigure_fips_task_error(self):
        """Test the PreconfigureFIPSTask task with a wrong policy."""
        task = PreconfigureFIPSTask(
            sysroot="/mnt/sysroot",
            payload_type=PAYLOAD_TYPE_DNF,
            fips_enabled=True,
        )

        with self.assertRaises(SecurityInstallationError) as cm:
            task.run()

        msg = "FIPS is not correctly set up in the installation environment."
        self.assertEqual(str(cm.exception), msg)

    @patch("pyanaconda.modules.security.installation.shutil")
    @patch("pyanaconda.modules.security.installation.util")
    def test_preconfigure_fips_task(self, mock_util, mock_shutil):
        """Test the PreconfigureFIPSTask task."""
        task = PreconfigureFIPSTask(
            sysroot="/mnt/sysroot",
            payload_type=PAYLOAD_TYPE_DNF,
            fips_enabled=True,
        )

        # Skip the checks.
        task._check_fips = lambda *args, **kwargs: True
        task.run()

        mock_util.mkdirChain.assert_called_once_with(
            "/mnt/sysroot/etc/crypto-policies/"
        )
        mock_shutil.copyfile.assert_called_once_with(
            "/etc/crypto-policies/config",
            "/mnt/sysroot/etc/crypto-policies/config"
        )
        mock_shutil.copytree.assert_called_once_with(
            "/etc/crypto-policies/back-ends/",
            "/mnt/sysroot/etc/crypto-policies/back-ends/",
            symlinks=True
        )

    def test_configure_fips_task_disabled(self):
        """Test the ConfigureFIPSTask task with disabled FIPS."""
        task = ConfigureFIPSTask(
            sysroot="/mnt/sysroot",
            fips_enabled=False,
        )

        with self.assertLogs(level="DEBUG") as cm:
            task.run()

        msg = "FIPS is not enabled. Skipping."
        self.assertTrue(any(map(lambda x: msg in x, cm.output)))

    @patch("pyanaconda.modules.security.installation.conf")
    def test_configure_fips_task_image(self, mock_conf):
        """Test the ConfigureFIPSTask task with image."""
        task = ConfigureFIPSTask(
            sysroot="/mnt/sysroot",
            fips_enabled=True,
        )

        mock_conf.target.is_hardware = False
        mock_conf.target.type = TargetType.IMAGE

        with self.assertLogs(level="DEBUG") as cm:
            task.run()

        msg = "Don't set up FIPS on IMAGE."
        self.assertTrue(any(map(lambda x: msg in x, cm.output)))

    @patch("pyanaconda.modules.security.installation.util")
    def test_configure_fips_task(self, mock_util):
        """Test the ConfigureFIPSTask task."""
        task = ConfigureFIPSTask(
            sysroot="/mnt/sysroot",
            fips_enabled=True,
        )

        task.run()

        mock_util.execWithRedirect.assert_called_once_with(
            "fips-mode-setup",
            ["--enable", "--no-bootcfg"],
            root="/mnt/sysroot"
        )
