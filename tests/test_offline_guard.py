import socket

import pytest

from tests.conftest import LiveNetworkBlocked


def test_live_network_is_blocked_in_tests():
    with pytest.raises(LiveNetworkBlocked):
        socket.create_connection(("trackon.in", 443), timeout=1)
