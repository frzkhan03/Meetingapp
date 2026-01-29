// Whiteboard functionality
var whiteBoardProperties = {
    isPresent: 0,
    isByYou: 0
};

var canvas, ctx;
var isDrawing = false;
var currentColor = '#ffffff';

const shareWhiteboardbtn = document.getElementById('white-board-btn');
const canvasArea = document.getElementById('canvas-area');

function createCanvas() {
    canvas = document.createElement('canvas');
    canvas.width = 800;
    canvas.height = 600;
    canvas.style.backgroundColor = '#1a1a2e';
    canvasArea.appendChild(canvas);
    canvasArea.style.display = 'block';

    ctx = canvas.getContext('2d');
    ctx.strokeStyle = currentColor;
    ctx.lineWidth = 3;
    ctx.lineCap = 'round';

    // Create color picker
    const colorPicker = document.createElement('input');
    colorPicker.type = 'color';
    colorPicker.id = 'colorPicker';
    colorPicker.value = currentColor;
    colorPicker.style.cssText = 'position: fixed; bottom: 100px; left: 50%; transform: translateX(-50%); z-index: 160;';
    document.body.appendChild(colorPicker);

    colorPicker.addEventListener('change', (e) => {
        currentColor = e.target.value;
        ctx.strokeStyle = currentColor;
        socketWrapper.emit('colorchange', { color: currentColor });
    });

    // Mouse events
    canvas.addEventListener('mousedown', handleMouseDown);
    canvas.addEventListener('mousemove', handleMouseMove);
    canvas.addEventListener('mouseup', handleMouseUp);
    canvas.addEventListener('mouseleave', handleMouseUp);

    whiteBoardProperties.isPresent = 1;
}

function deleteCanvas() {
    if (canvas) {
        canvas.remove();
        canvas = null;
        ctx = null;
    }
    const colorPicker = document.getElementById('colorPicker');
    if (colorPicker) {
        colorPicker.remove();
    }
    canvasArea.style.display = 'none';
    whiteBoardProperties.isPresent = 0;
    whiteBoardProperties.isByYou = 0;
}

function handleMouseDown(e) {
    isDrawing = true;
    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    ctx.beginPath();
    ctx.moveTo(x, y);

    socketWrapper.emit('mousedown', { clientX: x, clientY: y });
}

function handleMouseMove(e) {
    if (!isDrawing) return;

    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    ctx.lineTo(x, y);
    ctx.stroke();

    socketWrapper.emit('mousemove', { clientX: x, clientY: y });
}

function handleMouseUp(e) {
    if (isDrawing) {
        isDrawing = false;
        socketWrapper.emit('mouseup', {});
    }
}

// Remote drawing handlers
function remoteMouseDown(data) {
    if (!ctx) return;
    ctx.beginPath();
    ctx.moveTo(data.clientX, data.clientY);
}

function remoteMouseMove(data) {
    if (!ctx) return;
    ctx.lineTo(data.clientX, data.clientY);
    ctx.stroke();
}

function remoteMouseUp() {
    // Nothing needed
}

function remoteColorChange(color) {
    if (ctx) {
        ctx.strokeStyle = color;
        currentColor = color;
        const colorPicker = document.getElementById('colorPicker');
        if (colorPicker) {
            colorPicker.value = color;
        }
    }
}

// Button handler (only for moderators)
if (shareWhiteboardbtn) {
    shareWhiteboardbtn.addEventListener('click', () => {
        if (whiteBoardProperties.isPresent) {
            if (whiteBoardProperties.isByYou) {
                deleteCanvas();
                socketWrapper.emit('whiteboardclosed', {});
            }
        } else {
            socketWrapper.emit('whiteboardshared', {});
            createCanvas();
            whiteBoardProperties.isByYou = 1;
        }
    });
}

// Socket events for whiteboard
socketWrapper.on('whiteboardshared', () => {
    if (!whiteBoardProperties.isPresent) {
        createCanvas();
    }
});

socketWrapper.on('whiteboardclosed', () => {
    deleteCanvas();
});

socketWrapper.on('mousedown', (data) => {
    if (data && data.clientX !== undefined) {
        remoteMouseDown(data);
    }
});

socketWrapper.on('mousemove', (data) => {
    if (data && data.clientX !== undefined) {
        remoteMouseMove(data);
    }
});

socketWrapper.on('mouseup', () => {
    remoteMouseUp();
});

socketWrapper.on('colorchange', (data) => {
    if (data && data.color) {
        remoteColorChange(data.color);
    }
});
