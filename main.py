import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import tkinter as tk
from gui import RobloxHelperApp

if __name__ == "__main__":
    root = tk.Tk()
    app = RobloxHelperApp(root)
    root.mainloop()
