"""Portable invocation of the frozen static tool shipped beside this file."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent/'vendor/src'))
from analog_evidence.cli import main
if __name__=='__main__':sys.exit(main())
