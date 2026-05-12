from typing import Iterator, Optional

import numpy as np

from .const import EVENT_INIT
from .core import Client as _BaseClient


class Client(_BaseClient):
    """Generator-style scrcpy client.

    Same wire protocol and control surface as :class:`scrcpy.core.Client`, but
    ``start()`` returns an iterator that yields frames for worker-style
    consumers (see ``workers.thread_worker`` / ``workers.process_worker``).
    """

    def __init__(self, *args, bitrate: int = 16000000, **kwargs):
        # Workers historically default to a higher bitrate for the per-frame
        # processing path; keep that as the only behavioral override.
        super().__init__(*args, bitrate=bitrate, **kwargs)

    def start(self) -> Iterator[Optional[np.ndarray]]:
        """Deploy the server, hand-shake, then yield frames until stop().

        Yields ``None`` on transient backpressure (when ``block_frame`` is
        False) so callers can poll for stop flags between frames. Stops
        silently when the socket closes — keeping the historical contract
        that downstream workers rely on; truly fatal errors still bubble up
        from :meth:`_iter_frames`.
        """
        assert self.alive is False

        try:
            self._deploy_server()
            self._init_server_connection()
        except Exception:
            self.stop()
            raise

        self.alive = True
        self._send_to_listeners(EVENT_INIT)
        yield from self._iter_frames()
