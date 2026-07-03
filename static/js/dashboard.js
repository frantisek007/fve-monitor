// static/js/dashboard.js

// Premenné pre ukladanie aktuálnych hodnôt
let currentStartDate = '';
let currentEndDate = '';
let currentPoint = '';

// Funkcia na vynulovanie všetkých hodnôt
function resetAllValues() {
    document.getElementById('batteryFill').style.height = '0%';
    document.getElementById('batteryLevel').textContent = '--%';
    document.getElementById('batteryKwh').textContent = '--';
    document.getElementById('batteryCapacity').textContent = '0';
    document.getElementById('totalProduction').textContent = '-- kWh';
    document.getElementById('totalConsumption').textContent = '-- kWh';
    document.getElementById('netBalance').textContent = '-- kWh';
    document.getElementById('lastUpdate').textContent = '--';
}

// Funkcia na kontrolu zmien
function checkForChanges() {
    const startDate = document.getElementById('startDate').value;
    const endDate = document.getElementById('endDate').value;
    const point = document.getElementById('pointSelect').value;
    
    // Ak sa zmenil dátum alebo odberné miesto, vynulujeme hodnoty
    if (startDate !== currentStartDate || endDate !== currentEndDate || point !== currentPoint) {
        resetAllValues();
        currentStartDate = startDate;
        currentEndDate = endDate;
        currentPoint = point;
    }
}

// Funkcia na načítanie stavu
function loadStatus() {
    const startDate = document.getElementById('startDate').value;
    const endDate = document.getElementById('endDate').value;
    const point = document.getElementById('pointSelect').value;
    
    // Ak sa zmenil dátum alebo odberné miesto, vynulujeme hodnoty
    if (startDate !== currentStartDate || endDate !== currentEndDate || point !== currentPoint) {
        resetAllValues();
        currentStartDate = startDate;
        currentEndDate = endDate;
        currentPoint = point;
        return;
    }
    
    fetch('/api/battery-status')
    .then(r => r.json())
    .then(data => {
        if (data.error) return;
        
        document.getElementById('batteryFill').style.height = data.current_percent + '%';
        document.getElementById('batteryLevel').textContent = Math.round(data.current_percent) + '%';
        document.getElementById('batteryKwh').textContent = Math.round(data.current_kwh);
        document.getElementById('batteryCapacity').textContent = data.battery_capacity_kwh;
        document.getElementById('totalProduction').textContent = data.total_production + ' kWh';
        document.getElementById('totalConsumption').textContent = data.total_consumption + ' kWh';
        document.getElementById('netBalance').textContent = data.net_balance + ' kWh';
        document.getElementById('lastUpdate').textContent = data.last_update;
    });
}

// Funkcia na synchronizáciu dát
function syncData() {
    const startDate = document.getElementById('startDate').value;
    const endDate = document.getElementById('endDate').value;
    const pointAlias = document.getElementById('pointSelect').value;
    
    // Vynulujeme hodnoty pred načítaním
    resetAllValues();
    
    // Zobrazíme spinner
    document.getElementById('syncSpinner').style.display = 'inline-block';
    document.getElementById('syncText').textContent = 'Nacitavam...';
    document.getElementById('syncBtn').disabled = true;
    
    // Uložíme aktuálne hodnoty
    currentStartDate = startDate;
    currentEndDate = endDate;
    currentPoint = pointAlias;
    
    fetch('/api/sync-data', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            start_date: startDate, 
            end_date: endDate, 
            point_alias: pointAlias
        })
    })
    .then(r => r.json())
    .then(data => {
        document.getElementById('syncSpinner').style.display = 'none';
        document.getElementById('syncText').textContent = 'Sync';
        document.getElementById('syncBtn').disabled = false;
        
        if (data.error) {
            alert('Chyba: ' + data.error);
            return;
        }
        
        loadStatus();
    })
    .catch(e => {
        document.getElementById('syncSpinner').style.display = 'none';
        document.getElementById('syncText').textContent = 'Sync';
        document.getElementById('syncBtn').disabled = false;
        alert('Chyba: ' + e);
    });
}

// Inicializácia
document.addEventListener('DOMContentLoaded', function() {
    currentStartDate = document.getElementById('startDate').value;
    currentEndDate = document.getElementById('endDate').value;
    currentPoint = document.getElementById('pointSelect').value;
    
    loadStatus();
    
    document.getElementById('startDate').addEventListener('change', checkForChanges);
    document.getElementById('endDate').addEventListener('change', checkForChanges);
    document.getElementById('pointSelect').addEventListener('change', checkForChanges);
});

// Automatické obnovenie každých 30 sekúnd
setInterval(loadStatus, 30000);