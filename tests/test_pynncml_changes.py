#!/usr/bin/env python
"""
Test script to verify that changes to PyNNcml are reflected when using it.
"""
import sys
import os

# Add PyNNcml to path
# Go up one level from tests/ to root, then to PyNNcml
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'PyNNcml'))

try:
    import pynncml
    print("✓ Successfully imported pynncml")
    print(f"  Location: {pynncml.__file__}")
    print(f"  Version: {getattr(pynncml, '__version__', 'unknown')}")
    
    # Test: Check if we can access the module
    print("\n✓ Module structure accessible")
    print(f"  Available attributes: {[x for x in dir(pynncml) if not x.startswith('_')]}")
    
except ImportError as e:
    print(f"✗ Failed to import pynncml: {e}")
    sys.exit(1)

print("\n" + "="*50)
print("Test: Making a change to PyNNcml and verifying it works")
print("="*50)

