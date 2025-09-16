import sys

# Вывод всех аргументов командной строки
print("Тестовый скрипт с выводом аргументов командной строки:")
for i, arg in enumerate(sys.argv):
    if i == 0:
        print(f"  [{i}] = {arg} (имя скрипта)")
    else:
        print(f"  [{i}] = {arg}")



import argparse

parser = argparse.ArgumentParser(description="Вывод переданных аргументов")
parser.add_argument('--test', type=str, help='Строка')
parser.add_argument('--test_int', type=int, help='Число')
parser.add_argument('-t', type=str, help='Число')
parser.add_argument('args', nargs='*', help='Дополнительные аргументы')

args = parser.parse_args()

print("Переданные аргументы:")
print(f"  test = {args.test}")
print(f"  test_int = {args.test_int}")
print(f"  t = {args.t}")
print(f"  extra args = {args.args}")