/* static/admin/js/tenant_admin.js */
document.addEventListener('DOMContentLoaded', function() {
    // Color picker enhancements
    const colorPickers = document.querySelectorAll('.color-picker');
    colorPickers.forEach(picker => {
        const parent = picker.closest('.form-row');
        if (parent) {
            // Add color preview next to picker
            const preview = document.createElement('div');
            preview.className = 'color-preview';
            preview.style.cssText = `
                width: 30px;
                height: 30px;
                border-radius: 4px;
                border: 1px solid #ccc;
                margin-left: 10px;
                display: inline-block;
                vertical-align: middle;
                cursor: pointer;
            `;
            preview.style.backgroundColor = picker.value;
            
            picker.parentNode.insertBefore(preview, picker.nextSibling);
            
            // Update preview when color changes
            picker.addEventListener('input', function() {
                preview.style.backgroundColor = this.value;
            });
            
            // Click preview to open picker
            preview.addEventListener('click', function() {
                picker.click();
            });
        }
    });
    
    // Generate complementary colors
    const generateColorsBtn = document.createElement('button');
    generateColorsBtn.type = 'button';
    generateColorsBtn.className = 'button';
    generateColorsBtn.textContent = 'Generate Color Palette';
    generateColorsBtn.style.marginTop = '10px';
    
    const primaryColorField = document.querySelector('#id_primary_color');
    if (primaryColorField) {
        const parentRow = primaryColorField.closest('.form-row');
        if (parentRow) {
            parentRow.appendChild(generateColorsBtn);
            
            generateColorsBtn.addEventListener('click', function() {
                const primaryColor = primaryColorField.value;
                if (primaryColor && primaryColor.length === 7) {
                    // Generate complementary colors
                    const secondary = generateComplementary(primaryColor);
                    const accent = generateAccent(primaryColor);
                    
                    // Fill in other color fields
                    document.querySelector('#id_secondary_color').value = secondary;
                    document.querySelector('#id_accent_color').value = accent;
                    
                    // Trigger input events to update previews
                    document.querySelectorAll('.color-picker').forEach(picker => {
                        picker.dispatchEvent(new Event('input'));
                    });
                    
                    alert('Color palette generated successfully!');
                } else {
                    alert('Please set a valid primary color first (e.g., #4361ee)');
                }
            });
        }
    }
    
    function generateComplementary(hex) {
        // Simple complementary color generation
        let r = parseInt(hex.slice(1, 3), 16);
        let g = parseInt(hex.slice(3, 5), 16);
        let b = parseInt(hex.slice(5, 7), 16);
        
        // Convert to HSL, rotate hue by 180 degrees
        r = (255 - r).toString(16).padStart(2, '0');
        g = (255 - g).toString(16).padStart(2, '0');
        b = (255 - b).toString(16).padStart(2, '0');
        
        return `#${r}${g}${b}`;
    }
    
    function generateAccent(hex) {
        // Generate an accent color (warm color)
        let r = parseInt(hex.slice(1, 3), 16);
        let g = parseInt(hex.slice(3, 5), 16);
        let b = parseInt(hex.slice(5, 7), 16);
        
        // Increase red component for warmth
        r = Math.min(255, r + 80).toString(16).padStart(2, '0');
        g = Math.max(0, g - 40).toString(16).padStart(2, '0');
        b = Math.max(0, b - 40).toString(16).padStart(2, '0');
        
        return `#${r}${g}${b}`;
    }
});