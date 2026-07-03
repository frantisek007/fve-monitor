import sqlite3
conn = sqlite3.connect('fve.db')
c = conn.cursor()
c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='energy_history'")
if c.fetchone():
    print('Tabuľka energy_history existuje')
else:
    print('Tabuľka energy_history neexistuje')
conn.close()
