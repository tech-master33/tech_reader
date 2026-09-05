import uiautomation as auto

def test_uia():
    print("Testing uiautomation...")
    # List top level windows
    for control in auto.GetRootControl().GetChildren():
        name = control.Name.encode('utf-8', errors='ignore').decode('utf-8')
        print(f"Window: {name}")

if __name__ == "__main__":
    test_uia()
