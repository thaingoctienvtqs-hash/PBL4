"""Isolated launcher/E2E gates: no subprocess, ports, SQL, model, or camera."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from debug.full_integration import launch_test as launcher
from debug.full_integration import software_e2e as e2e

class LauncherSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/"logs").mkdir()
        (self.root/"tmp").mkdir()
        self.config={"profile":"ARTGUARD_INTEGRATION_TEST","database":{"name":"ArtGuard_Integration_TEST"}}
        self.save()
    def save(self):
        (self.root/"integration_config.json").write_text(json.dumps(self.config),encoding="utf8")
    def test_wrong_profile_stops_before_port_or_process(self):
        self.config["profile"]="PRODUCTION";self.save()
        with patch.object(launcher,"check_port") as port,patch.object(launcher.subprocess,"Popen") as process:
            with self.assertRaises(RuntimeError):launcher.start(self.root,"backend")
        port.assert_not_called();process.assert_not_called()
    def test_production_database_stops_before_port_or_process(self):
        self.config["database"]["name"]="pbl4_art_guard";self.save()
        with patch.object(launcher,"check_port") as port,patch.object(launcher.subprocess,"Popen") as process:
            with self.assertRaises(RuntimeError):launcher.start(self.root,"backend")
        port.assert_not_called();process.assert_not_called()
    def test_missing_bootstrap_stops_before_port_or_process(self):
        with patch.object(launcher,"check_port") as port,patch.object(launcher.subprocess,"Popen") as process:
            with self.assertRaisesRegex(RuntimeError,"successful TEST"):launcher.start(self.root,"backend")
        port.assert_not_called();process.assert_not_called()
    def test_failed_bootstrap_report_does_not_pass_gate(self):
        (self.root/"logs/sql_admin_bootstrap_fixture.json").write_text(json.dumps({"status":"FAILED","database":"ArtGuard_Integration_TEST"}))
        with patch.object(launcher,"check_port") as port,patch.object(launcher.subprocess,"Popen") as process:
            with self.assertRaises(RuntimeError):launcher.start(self.root,"backend")
        port.assert_not_called();process.assert_not_called()
    def test_production_bootstrap_report_does_not_pass_gate(self):
        (self.root/"logs/sql_admin_bootstrap_fixture.json").write_text(json.dumps({"status":"TEST_SCHEMA_AND_SEED_READY","database":"pbl4_art_guard"}))
        with patch.object(launcher,"check_port") as port,patch.object(launcher.subprocess,"Popen") as process:
            with self.assertRaises(RuntimeError):launcher.start(self.root,"backend")
        port.assert_not_called();process.assert_not_called()
    def test_repository_run_refused(self):
        with self.assertRaisesRegex(RuntimeError,"External TEST"):launcher.load(launcher.ROOT)
    def test_stop_reused_pid_refused(self):
        record={"pid":123,"identity":{"CommandLine":"old"}}
        (self.root/"process_registry.jsonl").write_text(json.dumps(record)+"\n")
        with patch.object(launcher,"identity",return_value={"CommandLine":"new"}),patch.object(launcher.subprocess,"run") as stop:
            launcher.stop(self.root)
        stop.assert_not_called()
    def test_e2e_http_targets_loopback_and_disables_redirects(self):
        response=MagicMock();response.status=200;response.read.return_value=b"{}"
        opener=MagicMock();opener.open.return_value.__enter__.return_value=response
        with patch.object(e2e,"build_opener",return_value=opener) as factory:
            status,_,_=e2e.request("/api/v1/alerts")
        self.assertEqual(status,200)
        request=opener.open.call_args.args[0]
        self.assertEqual(request.full_url,"http://127.0.0.1:8101/api/v1/alerts")
        self.assertTrue(any(isinstance(handler,e2e.NoRedirect) for handler in factory.call_args.args))

if __name__=="__main__":unittest.main()
