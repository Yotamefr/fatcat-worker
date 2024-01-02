import os
import socket
from fatcat_utils import FatCat
from .__init__ import Worker


def main():
    fatcat = FatCat(f"{os.getenv('FATCAT_LOGGER_NAME', socket.gethostname())}")
    worker = Worker(fatcat)
    fatcat.add_plugin(worker)
    fatcat.run()


if __name__ == "__main__":
    main()
