import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import resolve as R, jvm
vm = R.CarVM(jvm.Index(sys.argv[1]), R.natives())
box, s, m, y, c = map(int, sys.argv[2:7])
orig = vm.run
def run(meth, this, args):
    print("  " * vm.depth + f"{meth.cls.rsplit('.',1)[-1]}.{meth.name}{tuple(a if isinstance(a,(int,str)) else type(a).__name__ for a in args)}")
    return orig(meth, this, args)
vm.run = run
d = R.describe(vm, box, s, m, y, c, 0)
print(R.resolve(vm, d))
