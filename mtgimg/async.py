import threading

class Resolver(threading.Thread):
	def __init__(self):
		super().__init__()
		self._resolve = None
		self._reject = None
	def __call__(self, resolve, reject):
		self._resolve = resolve
		self._reject = reject
		self.start()