"""
Specialized test configuration for GitHub Actions CI/CD
Handles cases where Windows-specific dependencies are not available
"""

import os
import sys
import pytest
import platform

# Add app directory to Python path
app_dir = os.path.join(os.path.dirname(__file__), 'app')
if app_dir not in sys.path:
    sys.path.insert(0, app_dir)

def pytest_configure(config):
    """Configure pytest for CI environment"""
    # Add custom markers
    config.addinivalue_line("markers", "ci_skip: skip test in CI environment")
    config.addinivalue_line("markers", "windows_only: only run on Windows")
    config.addinivalue_line("markers", "requires_win32com: requires Windows COM objects")

def pytest_collection_modifyitems(config, items):
    """Modify test collection based on environment"""
    
    # Skip Windows-specific tests on non-Windows platforms
    if platform.system() != "Windows":
        skip_windows = pytest.mark.skip(reason="Windows-only test")
        for item in items:
            if "windows_only" in item.keywords:
                item.add_marker(skip_windows)
    
    # Skip COM-dependent tests in CI if win32com is not available
    try:
        import win32com.client
        win32com_available = True
    except ImportError:
        win32com_available = False
    
    if not win32com_available:
        skip_com = pytest.mark.skip(reason="win32com not available")
        for item in items:
            if "requires_win32com" in item.keywords:
                item.add_marker(skip_com)
    
    # Skip CI-incompatible tests
    if os.environ.get('CI'):
        skip_ci = pytest.mark.skip(reason="Skipped in CI environment")
        for item in items:
            if "ci_skip" in item.keywords:
                item.add_marker(skip_ci)

@pytest.fixture(autouse=True)
def mock_win32com_if_unavailable(monkeypatch):
    """Mock win32com.client if not available (for CI testing)"""
    try:
        import win32com.client
    except ImportError:
        # Create a mock win32com module for testing
        class MockSpeaker:
            def __init__(self):
                self.Volume = 100
                self.Voice = type('Voice', (), {'GetDescription': lambda: 'Mock Voice'})()
            
            def GetVoices(self):
                return [type('Voice', (), {'GetDescription': lambda: 'Mock Voice'})()]
            
            def Speak(self, text, flags=0):
                pass
        
        class MockWin32Com:
            @staticmethod
            def Dispatch(prog_id):
                if prog_id == "SAPI.SpVoice":
                    return MockSpeaker()
                return None
        
        # Mock the win32com.client module
        mock_module = type('MockModule', (), {'client': MockWin32Com()})()
        monkeypatch.setattr(sys.modules, 'win32com', mock_module)
        if 'win32com.client' not in sys.modules:
            sys.modules['win32com.client'] = MockWin32Com()

@pytest.fixture
def temp_elite_directory(tmp_path):
    """Create a temporary Elite Dangerous directory structure for testing"""
    elite_dir = tmp_path / "Elite Dangerous"
    elite_dir.mkdir()
    
    # Create mock files
    (elite_dir / "Journal.2025-10-25T120000.01.log").write_text('{"timestamp":"2025-10-25T12:00:00Z","event":"Fileheader"}')
    (elite_dir / "Cargo.json").write_text('{"timestamp":"2025-10-25T12:00:00Z","event":"Cargo","Count":0,"Inventory":[]}')
    (elite_dir / "Status.json").write_text('{"timestamp":"2025-10-25T12:00:00Z","event":"Status","Flags":0}')
    
    return str(elite_dir)

@pytest.fixture
def mock_config_file(tmp_path, monkeypatch):
    """Create a temporary config file for testing"""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "config.json"
    
    config_content = {
        "config_version": "4.1.7",
        "tts_volume": 100,
        "va_folder": "",
        "window": {"geometry": "1100x680+100+100", "zoomed": False},
        "tts_voice": "Mock Voice"
    }
    
    import json
    config_file.write_text(json.dumps(config_content, indent=2))
    
    # Mock the config path
    monkeypatch.setenv('ELITEMINING_CONFIG_PATH', str(config_file))
    
    return str(config_file)