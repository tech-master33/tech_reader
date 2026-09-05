from comtypes import client
import comtypes.gen.UIAutomationClient as UIA
import time

def test_comtypes_uia():
    print("Initializing UIA via comtypes...")
    
    # Initialize the UIA COM object
    uia = client.CreateObject(UIA.CUIAutomation)
    
    print("Monitoring focus... (Press Ctrl+C to stop)")
    last_name = ""
    
    while True:
        try:
            # Get the focused element
            focused_element = uia.GetFocusedElement()
            
            # Get the name property
            name = focused_element.CurrentName
            
            if name and name != last_name:
                print(f"Focused control changed to: {name}")
                last_name = name
                
        except Exception as e:
            print(f"Error: {e}")
        
        time.sleep(0.5)

if __name__ == "__main__":
    test_comtypes_uia()
