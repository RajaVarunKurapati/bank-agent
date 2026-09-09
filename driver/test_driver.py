"""Quick manual check that the driver can see and act. Not part of the agent."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from driver.surface_driver import SurfaceDriver

d = SurfaceDriver(headless=False)
d.navigate("http://127.0.0.1:5000")

print("=== What the agent sees on the home page ===")
print(d.observe()["elements"])

# drive the happy path by hand
d.type("12345", role="textbox", name="Member ID:")
d.click(name="Search")
d.page.wait_for_timeout(1000)

print("\n=== Page text after search (includes iframe) ===")
print(d.read_text())

input("\nPress Enter to close the browser...")
d.close()