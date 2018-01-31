
def greatest_common_denominator(a: int, b: int):
	if a == b:
		return b
	elif a>b:
		return greatest_common_denominator(a-b, b)
	else:
		return greatest_common_denominator(a, b-a)

def simplify(denominator: int, enumerator: int):
	gcd = greatest_common_denominator(denominator, enumerator)
	return denominator//gcd, enumerator//gcd

def power(base: int, exponent: int):
	if exponent == 0:
		return 0
	elif exponent == 1:
		return base
	else:
		return power(base, exponent-1) * base

def fibbonacci(n: int):
	if n < 1:
		return 0
	elif n == 1:
		return 1
	else:
		return fibbonacci(n-1) + fibbonacci(n-2)

def factorial(n: int):
	if n <= 1:
		return 1
	else:
		return n * factorial(n-1)

if __name__ == '__main__':
	print(simplify(40, 10))