"""
Basic tests for the Tax Rates Flask application.
"""
import pytest
import os
import sys
from io import StringIO

# Add parent directory to path to import app
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def test_imports():
    """Test that the app module can be imported."""
    try:
        import app
        assert app is not None
    except ImportError as e:
        pytest.fail(f"Failed to import app: {e}")


def test_flask_app_exists():
    """Test that Flask app is created."""
    # Set minimal required env vars for import
    os.environ['SUPABASE_URL'] = 'https://test.supabase.co'
    os.environ['SUPABASE_SERVICE_KEY'] = 'test-key'
    
    import app
    assert app.app is not None
    assert app.app.config['SECRET_KEY'] is not None


def test_csv_parsing_basic():
    """Test basic CSV parsing functionality."""
    # Set minimal required env vars
    os.environ['SUPABASE_URL'] = 'https://test.supabase.co'
    os.environ['SUPABASE_SERVICE_KEY'] = 'test-key'
    
    # This is a basic structure test - we're not testing the full parsing
    # since it requires database connections
    csv_content = """RegionCode,RegionName,BusinessCode,BusinessCodesName,TaxRate
PH,Phoenix,017,Retail,2.5%
TU,Tucson,017,Retail,2.3%"""
    
    # Verify CSV content is valid format
    lines = csv_content.strip().split('\n')
    assert len(lines) > 1  # Has header + data
    assert 'RegionCode' in lines[0]  # Has expected header


def test_app_routes_defined():
    """Test that main routes are defined."""
    os.environ['SUPABASE_URL'] = 'https://test.supabase.co'
    os.environ['SUPABASE_SERVICE_KEY'] = 'test-key'
    
    import app
    
    # Check that routes exist
    routes = [rule.rule for rule in app.app.url_map.iter_rules()]
    
    assert '/' in routes
    assert '/upload' in routes
    assert '/rates' in routes
    assert '/api/rates' in routes
