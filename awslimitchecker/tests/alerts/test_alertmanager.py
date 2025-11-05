"""
awslimitchecker/tests/alerts/test_alertmanager.py

The latest version of this package is available at:
<https://github.com/jantman/awslimitchecker>

################################################################################
Copyright 2015-2019 Jason Antman <jason@jasonantman.com>

    This file is part of awslimitchecker, also known as awslimitchecker.

    awslimitchecker is free software: you can redistribute it and/or modify
    it under the terms of the GNU Affero General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    awslimitchecker is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU Affero General Public License for more details.

    You should have received a copy of the GNU Affero General Public License
    along with awslimitchecker.  If not, see <http://www.gnu.org/licenses/>.

The Copyright and Authors attributions contained herein may not be removed or
otherwise altered, except to add the Author attribution of a contributor to
this work. (Additional Terms pursuant to Section 7b of the AGPL v3)
################################################################################
While not legally required, I sincerely request that anyone who finds
bugs please submit them at <https://github.com/jantman/awslimitchecker> or
to me via email, and that you send any contributions or improvements
either as a pull request on GitHub, or to me via email.
################################################################################

AUTHORS:
Jason Antman <jason@jasonantman.com> <http://www.jasonantman.com>
################################################################################
"""

import sys
from awslimitchecker.alerts.alertmanager import AlertManager
from awslimitchecker.limit import AwsLimit, AwsLimitUsage
import pytest
from datetime import datetime, timedelta

# https://code.google.com/p/mock/issues/detail?id=249
# py>=3.4 should use unittest.mock not the mock package on pypi
if (
        sys.version_info[0] < 3 or
        sys.version_info[0] == 3 and sys.version_info[1] < 4
):
    from mock import patch, call, Mock, DEFAULT
else:
    from unittest.mock import patch, call, Mock, DEFAULT

pbm = 'awslimitchecker.alerts.alertmanager'
pb = '%s.AlertManager' % pbm


class TestInit(object):

    @patch.dict(
        'os.environ',
        {'ALERTMANAGER_ENDPOINTS': 'http://alertmanager:9093'},
        clear=True
    )
    def test_env_var_only(self):
        cls = AlertManager('us-east-1')
        assert cls._region_name == 'us-east-1'
        assert cls._endpoints == 'http://alertmanager:9093'
        assert cls._alert_duration == '1800'
        assert cls._basic_auth_username is None
        assert cls._basic_auth_password is None

    @patch.dict('os.environ', {}, clear=True)
    def test_param_only(self):
        cls = AlertManager('us-west-2', endpoints='http://alertmanager1:9093')
        assert cls._region_name == 'us-west-2'
        assert cls._endpoints == 'http://alertmanager1:9093'
        assert cls._alert_duration == '1800'

    @patch.dict(
        'os.environ',
        {
            'ALERTMANAGER_ENDPOINTS': 'http://alertmanager:9093',
            'ALERTMANAGER_ALERT_DURATION': '3600',
            'ALERTMANAGER_BASIC_AUTH_USERNAME': 'user',
            'ALERTMANAGER_BASIC_AUTH_PASSWORD': 'pass'
        },
        clear=True
    )
    def test_all_env_vars(self):
        cls = AlertManager('eu-west-1')
        assert cls._region_name == 'eu-west-1'
        assert cls._endpoints == 'http://alertmanager:9093'
        assert cls._alert_duration == '3600'
        assert cls._basic_auth_username == 'user'
        assert cls._basic_auth_password == 'pass'

    @patch.dict('os.environ', {}, clear=True)
    def test_all_params(self):
        cls = AlertManager(
            'us-east-1',
            endpoints='http://alertmanager1:9093,http://alertmanager2:9093',
            alert_duration='7200',
            basic_auth_username='testuser',
            basic_auth_password='testpass'
        )
        assert cls._region_name == 'us-east-1'
        assert cls._endpoints == 'http://alertmanager1:9093,http://alertmanager2:9093'
        assert cls._alert_duration == '7200'
        assert cls._basic_auth_username == 'testuser'
        assert cls._basic_auth_password == 'testpass'

    @patch.dict('os.environ', {}, clear=True)
    def test_no_endpoints(self):
        with pytest.raises(RuntimeError) as exc:
            AlertManager('us-east-1')
        assert str(exc.value) == 'ERROR: AlertManager alert provider requires ' \
                                 'endpoints parameter or ALERTMANAGER_ENDPOINTS ' \
                                 'environment variable.'


class AlertManagerTester(object):

    def setup(self):
        with patch('%s.__init__' % pb) as m_init:
            m_init.return_value = None
            self.cls = AlertManager('us-east-1')
            self.cls._region_name = 'us-east-1'
            self.cls._endpoints = 'http://alertmanager:9093'
            self.cls._alert_duration = '1800'
            self.cls._basic_auth_username = 'user'
            self.cls._basic_auth_password = 'pass'


class TestSendEvent(AlertManagerTester):

    def test_success_single_endpoint(self):
        mock_http = Mock()
        mock_resp = Mock(status=200, data='{"status":"success"}')
        mock_http.request.return_value = mock_resp
        
        with patch('%s.urllib3.PoolManager' % pbm) as mock_pm:
            with patch('%s.datetime' % pbm) as mock_dt:
                mock_now = datetime(2025, 1, 15, 12, 0, 0)
                mock_dt.utcnow.return_value = mock_now
                mock_pm.return_value = mock_http
                self.cls._send_event('critical', 'Test alert')
        
        # Verify the request was made
        assert len(mock_http.request.mock_calls) == 1
        call_args = mock_http.request.mock_calls[0]
        assert call_args[1][0] == 'POST'
        assert call_args[1][1] == 'http://alertmanager:9093/api/v1/alerts'

    def test_success_multiple_endpoints(self):
        self.cls._endpoints = 'http://alertmanager1:9093,http://alertmanager2:9093'
        mock_http = Mock()
        mock_resp = Mock(status=200, data='{"status":"success"}')
        mock_http.request.return_value = mock_resp
        
        with patch('%s.urllib3.PoolManager' % pbm) as mock_pm:
            with patch('%s.datetime' % pbm) as mock_dt:
                mock_now = datetime(2025, 1, 15, 12, 0, 0)
                mock_dt.utcnow.return_value = mock_now
                mock_pm.return_value = mock_http
                self.cls._send_event('warning', 'Test warning')
        
        # Should make 2 requests (one per endpoint)
        assert len(mock_http.request.mock_calls) == 2

    def test_failure_non_200(self):
        mock_http = Mock()
        mock_resp = Mock(status=500, data='{"error":"internal error"}')
        mock_http.request.return_value = mock_resp
        
        with patch('%s.urllib3.PoolManager' % pbm) as mock_pm:
            with patch('%s.datetime' % pbm) as mock_dt:
                mock_now = datetime(2025, 1, 15, 12, 0, 0)
                mock_dt.utcnow.return_value = mock_now
                mock_pm.return_value = mock_http
                with pytest.raises(RuntimeError) as exc:
                    self.cls._send_event('critical', 'Test alert')
        
        assert 'Alert was not able to be sent' in str(exc.value)

    def test_failure_max_retry_error(self):
        import urllib3
        mock_http = Mock()
        mock_http.request.side_effect = urllib3.exceptions.MaxRetryError(
            pool=None, url='http://alertmanager:9093'
        )
        
        with patch('%s.urllib3.PoolManager' % pbm) as mock_pm:
            with patch('%s.datetime' % pbm) as mock_dt:
                mock_now = datetime(2025, 1, 15, 12, 0, 0)
                mock_dt.utcnow.return_value = mock_now
                mock_pm.return_value = mock_http
                with pytest.raises(RuntimeError) as exc:
                    self.cls._send_event('critical', 'Test alert')
        
        assert 'Alert was not able to be sent' in str(exc.value)

    def test_partial_success_multiple_endpoints(self):
        self.cls._endpoints = 'http://alertmanager1:9093,http://alertmanager2:9093'
        mock_http = Mock()
        # First succeeds, second fails
        mock_http.request.side_effect = [
            Mock(status=200, data='{"status":"success"}'),
            Mock(status=500, data='{"error":"failed"}')
        ]
        
        with patch('%s.urllib3.PoolManager' % pbm) as mock_pm:
            with patch('%s.datetime' % pbm) as mock_dt:
                mock_now = datetime(2025, 1, 15, 12, 0, 0)
                mock_dt.utcnow.return_value = mock_now
                mock_pm.return_value = mock_http
                # Should not raise since at least one succeeded
                self.cls._send_event('critical', 'Test alert')


class TestGenerateDescription(AlertManagerTester):

    def test_single_problem(self):
        mock_service = Mock()
        limit = AwsLimit('Test Limit', mock_service, 100, 80, 99)
        limit._set_api_limit(100)
        usage = AwsLimitUsage(limit, 95)
        limit._warnings = [usage]
        
        problems = {
            'EC2': {
                'Test Limit': limit
            }
        }
        
        result = self.cls._generate_description(problems)
        assert 'EC2/Test Limit' in result
        assert '(limit 100)' in result
        assert 'WARNING: 95' in result

    def test_multiple_problems(self):
        mock_service = Mock()
        limit1 = AwsLimit('Limit 1', mock_service, 100, 80, 99)
        limit1._set_api_limit(100)
        usage1 = AwsLimitUsage(limit1, 95)
        limit1._warnings = [usage1]
        
        limit2 = AwsLimit('Limit 2', mock_service, 50, 80, 99)
        limit2._set_api_limit(50)
        usage2 = AwsLimitUsage(limit2, 48)
        limit2._criticals = [usage2]
        
        problems = {
            'EC2': {
                'Limit 1': limit1,
                'Limit 2': limit2
            }
        }
        
        result = self.cls._generate_description(problems)
        assert 'EC2/Limit 1' in result
        assert 'EC2/Limit 2' in result
        assert 'WARNING: 95' in result
        assert 'CRITICAL: 48' in result


class TestOnSuccess(AlertManagerTester):

    def test_on_success(self):
        # Should do nothing
        self.cls.on_success(duration=1.23)
        # No exception means success


class TestOnCritical(AlertManagerTester):

    def test_with_exception(self):
        exc = Exception('Test exception')
        with pytest.raises(Exception) as raised_exc:
            self.cls.on_critical(None, None, exc=exc, duration=1.0)
        assert raised_exc.value == exc

    def test_with_problems(self):
        mock_service = Mock()
        limit = AwsLimit('Test Limit', mock_service, 100, 80, 99)
        limit._set_api_limit(100)
        usage = AwsLimitUsage(limit, 99)
        limit._criticals = [usage]
        
        problems = {
            'EC2': {
                'Test Limit': limit
            }
        }
        
        with patch.object(self.cls, '_send_event') as mock_send:
            self.cls.on_critical(problems, 'problem_str', duration=1.0)
        
        assert mock_send.call_count == 1
        assert mock_send.call_args[0][0] == 'critical'
        assert 'EC2/Test Limit' in mock_send.call_args[0][1]


class TestOnWarning(AlertManagerTester):

    def test_on_warning(self):
        mock_service = Mock()
        limit = AwsLimit('Test Limit', mock_service, 100, 80, 99)
        limit._set_api_limit(100)
        usage = AwsLimitUsage(limit, 85)
        limit._warnings = [usage]
        
        problems = {
            'RDS': {
                'Test Limit': limit
            }
        }
        
        with patch.object(self.cls, '_send_event') as mock_send:
            self.cls.on_warning(problems, 'problem_str', duration=2.5)
        
        assert mock_send.call_count == 1
        assert mock_send.call_args[0][0] == 'warning'
        assert 'RDS/Test Limit' in mock_send.call_args[0][1]

