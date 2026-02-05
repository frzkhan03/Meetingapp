// ================== WEBSOCKET CONNECTION WITH HEARTBEAT & RECONNECT ==================

const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const WS_HEARTBEAT_INTERVAL = 30000;  // Send ping every 30s
const WS_HEARTBEAT_TIMEOUT = 10000;   // Expect pong within 10s
const WS_MAX_RECONNECT_ATTEMPTS = 10;
const WS_BASE_RECONNECT_DELAY = 1000; // 1s, doubles each attempt

// Heartbeat manager for a WebSocket connection
function createHeartbeat(ws, label) {
    let pingTimer = null;
    let pongTimer = null;

    function start() {
        stop();
        pingTimer = setInterval(function() {
            if (ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'ping' }));
                pongTimer = setTimeout(function() {
                    console.warn(label + ': no pong received, closing connection');
                    ws.close(4000, 'Heartbeat timeout');
                }, WS_HEARTBEAT_TIMEOUT);
            }
        }, WS_HEARTBEAT_INTERVAL);
    }

    function onPong() {
        if (pongTimer) {
            clearTimeout(pongTimer);
            pongTimer = null;
        }
    }

    function stop() {
        if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }
        if (pongTimer) { clearTimeout(pongTimer); pongTimer = null; }
    }

    return { start: start, onPong: onPong, stop: stop };
}

// --- Room Socket ---
let socket = null;
let roomHeartbeat = null;
let roomReconnectAttempts = 0;
let roomReconnectTimer = null;

function connectRoomSocket() {
    if (roomReconnectTimer) { clearTimeout(roomReconnectTimer); roomReconnectTimer = null; }

    socket = new WebSocket(wsProtocol + '//' + window.location.host + '/ws/room/' + ROOM_ID + '/');
    roomHeartbeat = createHeartbeat(socket, 'RoomSocket');

    socket.onopen = function() {
        console.log('Room WebSocket connected');
        roomReconnectAttempts = 0;
        roomHeartbeat.start();
        socketWrapper.emit('join-room', {
            room_id: ROOM_ID,
            user_id: USER_ID,
            username: username,
            is_moderator: IS_MODERATOR
        });
        // Share participant info after join
        setTimeout(function() {
            socketWrapper.emit('share-info', {
                user_id: USER_ID,
                username: username,
                is_moderator: IS_MODERATOR
            });
        }, 1000);
    };

    socket.onmessage = function(e) {
        var data = JSON.parse(e.data);
        if (data.type === 'pong') {
            roomHeartbeat.onPong();
            return;
        }
        if (data.type === 'newuserjoined' || data.type === 'share-info' || data.type === 'newmessage') {
            socketWrapper.trigger(data.type, data);
        } else {
            socketWrapper.trigger(data.type, data.user_id || data.message || data.data || data);
        }
    };

    socket.onerror = function(e) {
        console.error('Room WebSocket error:', e);
    };

    socket.onclose = function(e) {
        console.log('Room WebSocket closed:', e.code, e.reason);
        roomHeartbeat.stop();
        if (e.code !== 4029 && roomReconnectAttempts < WS_MAX_RECONNECT_ATTEMPTS) {
            var baseDelay = WS_BASE_RECONNECT_DELAY * Math.pow(2, roomReconnectAttempts);
            var jitter = Math.random() * baseDelay * 0.5;
            var delay = Math.floor(baseDelay + jitter);
            console.log('Room reconnecting in ' + delay + 'ms (attempt ' + (roomReconnectAttempts + 1) + ')');
            roomReconnectTimer = setTimeout(function() {
                roomReconnectAttempts++;
                connectRoomSocket();
            }, delay);
        }
    };

    // Update global reference for moderator controls
    window.socket = socket;
}

// --- User Socket ---
let userSocket = null;
let userHeartbeat = null;
let userReconnectAttempts = 0;
let userReconnectTimer = null;

function connectUserSocket() {
    if (userReconnectTimer) { clearTimeout(userReconnectTimer); userReconnectTimer = null; }

    userSocket = new WebSocket(wsProtocol + '//' + window.location.host + '/ws/user/');
    userHeartbeat = createHeartbeat(userSocket, 'UserSocket');

    userSocket.onopen = function() {
        console.log('User WebSocket connected for alerts');
        userReconnectAttempts = 0;
        userHeartbeat.start();
    };

    userSocket.onmessage = function(e) {
        var data = JSON.parse(e.data);
        if (data.type === 'pong') {
            userHeartbeat.onPong();
            return;
        }
        if (data.type === 'alert') {
            console.log('Join request received from:', data.username, data.user_id);
            showJoinRequestModal(data.user_id, data.username, data.room_id);
        }
    };

    userSocket.onerror = function(e) {
        console.error('User WebSocket error:', e);
    };

    userSocket.onclose = function(e) {
        console.log('User WebSocket closed:', e.code, e.reason);
        userHeartbeat.stop();
        if (e.code !== 4029 && userReconnectAttempts < WS_MAX_RECONNECT_ATTEMPTS) {
            var baseDelay = WS_BASE_RECONNECT_DELAY * Math.pow(2, userReconnectAttempts);
            var jitter = Math.random() * baseDelay * 0.5;
            var delay = Math.floor(baseDelay + jitter);
            console.log('User socket reconnecting in ' + delay + 'ms (attempt ' + (userReconnectAttempts + 1) + ')');
            userReconnectTimer = setTimeout(function() {
                userReconnectAttempts++;
                connectUserSocket();
            }, delay);
        }
    };
}

// Socket wrapper to mimic Socket.io API
const socketWrapper = {
    callbacks: {},
    on: function(event, callback) {
        if (!this.callbacks[event]) {
            this.callbacks[event] = [];
        }
        this.callbacks[event].push(callback);
    },
    emit: function(event, data, extraData) {
        if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({
                type: event,
                data: typeof data === 'object' ? data : { value: data, extra: extraData }
            }));
        }
    },
    trigger: function(event, data) {
        if (this.callbacks[event]) {
            this.callbacks[event].forEach(cb => cb(data));
        }
    }
};

// Initialize both connections
connectRoomSocket();
connectUserSocket();

// Video Elements
const videoElement = document.getElementById('video-area');
let ActiveUsers = {};
let UserVideoOn = {};
let UserScreenShareOn = {};
let UserStreamwithId = {};
let UserIdName = {};
UserIdName[USER_ID] = username;
let USER_ID_ScreenShare;

// Layout state
let currentLayout = 'grid'; // 'grid', 'spotlight', or 'sidebar'
let pinnedVideoId = null;
let layoutBeforeScreenShare = null; // saved layout to restore when screen share ends

// PeerJS Setup with ICE servers for production
const iceConfig = {
    config: {
        iceServers: [
            { urls: 'stun:stun.l.google.com:19302' },
            { urls: 'stun:stun1.l.google.com:19302' },
            { urls: 'stun:stun2.l.google.com:19302' },
            { urls: 'stun:stun3.l.google.com:19302' },
            { urls: 'stun:stun4.l.google.com:19302' },
            { urls: 'stun:stun.relay.metered.ca:80' },
        ]
    }
};
const myPeer = new Peer(undefined, iceConfig);
var myPeer2;

myPeer.on('open', async function(id) {
    USER_ID = id;
    UserIdName[id] = username; // Update with new peer ID
    socketWrapper.emit('join-room', {
        room_id: ROOM_ID,
        user_id: id,
        username: username,
        is_moderator: IS_MODERATOR
    });
    console.log('My peer Id is:', id);
    ActiveUsers[id] = 1;

    myPeer2 = new Peer(USER_ID + 'ScreenShare', iceConfig);
    myPeer2.on('open', async (id) => {
        console.log('My other Peer id is:', id);
    });

    myPeer2.on('call', async function(call) {
        let userId = call.peer;
        console.log('I got a screen share call');
        await call.answer();
        call.on('stream', async function(stream) {
            if (stream) {
                console.log('Adding screen share stream');
                userId = userId.substring(0, userId.length - 11);
                await addVideoStream(stream, userId, 1);
            }
        });
    });
});

// Button and Video State
let ButtonDetails = {
    onVideoButton: 0,
    screenShareButton: 0,
};

let VideoDetails = {
    HighlightedVideo: undefined,
    myVideo: undefined,
    myScreenShare: undefined,
    myVideoStream: undefined,
    myScreenStream: undefined,
};

// Recording State
let RecordingDetails = {
    isRecording: false,
    mediaRecorder: null,
    recordedChunks: [],
    audioContext: null,
    audioDestination: null,
    audioSources: {},
    recordingCanvas: null,
    canvasContext: null,
    animationFrameId: null,
    startTime: null,
};

// Initialize Video Stream
let mediaReady = false;
let mediaReadyPromise = new Promise((resolve) => { window._resolveMediaReady = resolve; });

let initializeVideoStreamSetup = async () => {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({
            video: true,
            audio: true
        });
        VideoDetails.myVideoStream = stream;
        ButtonDetails.onVideoButton = 1;
        await addVideoStream(stream, USER_ID);
        mediaReady = true;
        window._resolveMediaReady();
    } catch (err) {
        console.error('Error accessing media devices:', err);
        alert('Could not access camera/microphone. Please check permissions.');
        mediaReady = true;
        window._resolveMediaReady();
    }
};
initializeVideoStreamSetup();

// Socket Event Handlers
socketWrapper.on('newuserjoined', async (data) => {
    // Handle both old format (just userId) and new format (object with user_id, username)
    let userId, newUsername, isModerator;
    if (typeof data === 'object') {
        userId = data.user_id;
        newUsername = data.username;
        isModerator = data.is_moderator;
    } else {
        userId = data;
    }

    console.log(`New user joined: ${userId}, username: ${newUsername}`);

    // Store their name if provided
    if (newUsername) {
        const displayName = isModerator ? newUsername + ' (Host)' : newUsername;
        UserIdName[userId] = displayName;
        ParticipantsInfo[userId] = {
            id: userId,
            username: newUsername,
            is_moderator: isModerator
        };
        // Update participants panel immediately
        updateParticipantsPanel();
    }

    displayNewUser(userId);
    playJoinSound();
    ActiveUsers[userId] = 1;
    ConnecttonewUser(userId, VideoDetails.myVideoStream);
    ConnecttonewUser(userId, VideoDetails.myScreenStream, 1);

    // Send our info to the new user
    setTimeout(() => {
        socketWrapper.emit('share-info', {
            user_id: USER_ID,
            username: username,
            is_moderator: IS_MODERATOR
        });
    }, 500);
});

socketWrapper.on('user-disconnected', async (userId) => {
    console.log('User disconnected:', userId);
    delete ActiveUsers[userId];
    delete UserVideoOn[userId];
    if (document.getElementById(userId)) {
        document.getElementById(userId).remove();
    }
    if (document.getElementById(userId + 'ScreenShare')) {
        document.getElementById(userId + 'ScreenShare').remove();
    }
    if (RecordingDetails.isRecording) {
        removeAudioSourceFromMix(userId);
    }
    updateParticipantCount();

    // If the pinned user (or their screen share) disconnected, pin another video
    if ((currentLayout === 'spotlight' || currentLayout === 'sidebar') &&
        (pinnedVideoId === userId || pinnedVideoId === userId + 'ScreenShare')) {
        const nextVideo = document.querySelector('#video-area .innervideo');
        if (nextVideo) {
            pinVideo(nextVideo.id);
        } else {
            pinnedVideoId = null;
        }
    }
});

let unreadChatCount = 0;

socketWrapper.on('newmessage', (data) => {
    const msg = typeof data === 'object' ? data.message : data;
    const senderName = (typeof data === 'object' && data.username) ? data.username : '';
    displaychat(msg, 0, senderName);

    const sidebar = document.getElementById('sidebar');
    if (!sidebar.classList.contains('active')) {
        unreadChatCount++;
        const badge = document.getElementById('chat-badge');
        badge.textContent = unreadChatCount > 99 ? '99+' : unreadChatCount;
        badge.style.display = 'flex';
    }
});

// Chat functionality
const submit = document.getElementById('submit');
submit.addEventListener('click', async () => {
    const text = document.getElementById('chatbox');
    if (text.value.trim()) {
        displaychat(text.value, 1, username);
        socketWrapper.emit('new-chat', { message: text.value, room_id: ROOM_ID, user_id: USER_ID, username: username });
        text.value = '';
    }
});

document.getElementById('chatbox').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        submit.click();
    }
});

function playJoinSound() {
    try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const notes = [523.25, 659.25, 783.99]; // C5, E5, G5 chord
        notes.forEach((freq, i) => {
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = 'sine';
            osc.frequency.value = freq;
            gain.gain.setValueAtTime(0, ctx.currentTime + i * 0.08);
            gain.gain.linearRampToValueAtTime(0.15, ctx.currentTime + i * 0.08 + 0.05);
            gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + i * 0.08 + 0.4);
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start(ctx.currentTime + i * 0.08);
            osc.stop(ctx.currentTime + i * 0.08 + 0.4);
        });
    } catch (e) {}
}

function displayNewUser(userId) {
    const message = document.createElement('div');
    message.setAttribute('class', 'userjoined');
    const displayName = getDisplayName(userId);
    message.textContent = displayName + ' has joined';
    const messageArea = document.getElementById('message-area');
    messageArea.appendChild(message);
    messageArea.scrollTop = messageArea.scrollHeight;
    updateParticipantCount();
}

function displaychat(chat, sender, senderName) {
    const message = document.createElement('div');
    message.setAttribute('class', sender ? 'chat-display-sender' : 'chat-display');

    if (senderName) {
        const nameEl = document.createElement('span');
        nameEl.className = 'chat-sender-name';
        nameEl.textContent = sender ? 'You' : senderName;
        message.appendChild(nameEl);
    }

    const textEl = document.createElement('span');
    textEl.className = 'chat-text';
    textEl.textContent = chat;
    message.appendChild(textEl);

    const messageArea = document.getElementById('message-area');
    messageArea.appendChild(message);
    messageArea.scrollTop = messageArea.scrollHeight;
}

function updateParticipantCount() {
    const count = Object.keys(ActiveUsers).length;
    const countElement = document.getElementById('participant-count');
    if (countElement) {
        countElement.textContent = count;
    }
}

// PeerJS Call Handler
myPeer.on('call', async function(call) {
    let userId = call.peer;
    console.log('Received call from:', userId);
    // Wait for getUserMedia to complete before answering
    if (!mediaReady) {
        await mediaReadyPromise;
    }
    await call.answer(VideoDetails.myVideoStream);
    call.on('stream', async function(stream) {
        if (stream) {
            await addVideoStream(stream, userId);
            ActiveUsers[userId] = 1;
            UserStreamwithId[userId] = stream;
        }
    });
});

// Connect to New User
async function ConnecttonewUser(userId, stream, isScreenShare) {
    if (!stream) return;

    if (isScreenShare) {
        let ScreenShareUser = userId + 'ScreenShare';
        if (ScreenShareUser === USER_ID_ScreenShare) return;

        let call = await myPeer2.call(ScreenShareUser, stream);
        if (call) {
            call.on('stream', async function(stream) {
                if (stream) {
                    await addVideoStream(stream, userId, 1);
                }
            });
        }
    } else {
        if (userId === USER_ID) return;

        let call = await myPeer.call(userId, stream);
        if (call) {
            call.on('stream', async function(stream) {
                if (stream) {
                    UserStreamwithId[userId] = stream;
                    await addVideoStream(stream, userId);
                }
            });
        }
    }
}

// Microphone Toggle
let micEnabled = true;
const micButton = document.getElementById('mic');
micButton.addEventListener('click', async () => {
    if (VideoDetails.myVideoStream) {
        const audioTracks = VideoDetails.myVideoStream.getAudioTracks();
        audioTracks.forEach(track => {
            track.enabled = !track.enabled;
            micEnabled = track.enabled;
        });

        if (micEnabled) {
            micButton.classList.remove('muted');
            micButton.title = 'Toggle Microphone (M)';
        } else {
            micButton.classList.add('muted');
            micButton.title = 'Unmute Microphone (M)';
        }

        socketWrapper.emit('mute-status', { room_id: ROOM_ID, user_id: USER_ID, is_muted: !micEnabled });
        updateMuteIndicator(USER_ID, !micEnabled);
    }
});

// Mute state indicator on video tiles
socketWrapper.on('user-mute-status', (data) => {
    const userId = data.user_id;
    const isMuted = data.is_muted;
    updateMuteIndicator(userId, isMuted);
});

function updateMuteIndicator(userId, isMuted) {
    const videoTile = document.getElementById(userId);
    if (!videoTile) return;

    let indicator = videoTile.querySelector('.muted-indicator');

    if (isMuted) {
        if (!indicator) {
            indicator = document.createElement('div');
            indicator.className = 'muted-indicator';
            indicator.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="1" y1="1" x2="23" y2="23"/><path d="M9 9v3a3 3 0 0 0 5.12 2.12M15 9.34V4a3 3 0 0 0-5.94-.6"/><path d="M17 16.95A7 7 0 0 1 5 12v-2m14 0v2c0 .76-.13 1.49-.35 2.17"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>';
            videoTile.appendChild(indicator);
        }
    } else {
        if (indicator) {
            indicator.remove();
        }
    }
}

// Video Toggle
const onVideo = document.getElementById('onVideo');
onVideo.addEventListener('click', async () => {
    if (ButtonDetails.onVideoButton === 0) {
        // Enable video tracks
        const videoTracks = VideoDetails.myVideoStream.getVideoTracks();
        videoTracks.forEach(track => track.enabled = true);

        const myVideoDiv = document.getElementById(USER_ID);
        if (myVideoDiv) {
            // Tile exists — just show the video and hide avatar
            myVideoDiv.classList.remove('camera-off');
            const videoEl = myVideoDiv.querySelector('video');
            if (videoEl) videoEl.style.display = '';
        } else {
            // Tile was removed (e.g. disconnect) — recreate
            delete UserVideoOn[USER_ID];
            await addVideoStream(VideoDetails.myVideoStream, USER_ID);
        }
        socketWrapper.emit('on-the-video', { user_id: USER_ID });
        ButtonDetails.onVideoButton = 1;
        onVideo.classList.remove('video-off');
        onVideo.title = 'Toggle Video (V)';
    } else {
        ButtonDetails.onVideoButton = 0;

        // Disable video tracks (not audio)
        const videoTracks = VideoDetails.myVideoStream.getVideoTracks();
        videoTracks.forEach(track => track.enabled = false);

        // Keep the tile — show avatar instead of removing
        const myVideoDiv = document.getElementById(USER_ID);
        if (myVideoDiv) {
            myVideoDiv.classList.add('camera-off');
            const videoEl = myVideoDiv.querySelector('video');
            if (videoEl) videoEl.style.display = 'none';
        }
        socketWrapper.emit('video-off', { user_id: USER_ID });
        onVideo.classList.add('video-off');
        onVideo.title = 'Turn On Video (V)';
    }
});

socketWrapper.on('on-the-video', (userId) => {
    // Don't process our own video-on events (we handle it locally)
    if (userId === USER_ID) return;

    const videoDiv = document.getElementById(userId);
    if (videoDiv) {
        // Tile exists — show video and hide avatar
        videoDiv.classList.remove('camera-off');
        const videoEl = videoDiv.querySelector('video');
        if (videoEl) videoEl.style.display = '';
    } else if (UserStreamwithId[userId]) {
        // Tile missing — recreate
        delete UserVideoOn[userId];
        addVideoStream(UserStreamwithId[userId], userId);
    }
});

socketWrapper.on('off-the-video', (userId) => {
    // Keep the tile — show avatar instead of removing
    const videoDiv = document.getElementById(userId);
    if (videoDiv) {
        videoDiv.classList.add('camera-off');
        const videoEl = videoDiv.querySelector('video');
        if (videoEl) videoEl.style.display = 'none';
    }
});

// Screen Share (only for moderators)
const screenShare = document.getElementById('screenShare');
if (screenShare) {
    screenShare.addEventListener('click', async () => {
        if (!myPeer2) {
            console.log('myPeer2 not defined');
            return;
        }

        if (!VideoDetails.myScreenShare) {
            try {
                const stream = await navigator.mediaDevices.getDisplayMedia({
                    video: { mediaSource: 'screen' }
                });
                if (stream) {
                    await addVideoStream(stream, USER_ID, 1);
                    VideoDetails.myScreenStream = stream;
                    for (let userId of Object.keys(ActiveUsers)) {
                        await ConnecttonewUser(userId, stream, 1);
                    }
                    ButtonDetails.screenShareButton = 1;

                    // Handle stream end
                    stream.getVideoTracks()[0].onended = () => {
                        stopScreenShare();
                    };
                }
            } catch (err) {
                console.error('Error sharing screen:', err);
            }
        } else {
            stopScreenShare();
        }
    });
}

function stopScreenShare() {
    ButtonDetails.screenShareButton = 0;
    if (VideoDetails.myScreenStream) {
        VideoDetails.myScreenStream.getTracks().forEach(track => track.stop());
    }
    VideoDetails.myScreenShare = undefined;
    UserScreenShareOn[USER_ID] = 0;
    socketWrapper.emit('screen-share-off', { user_id: USER_ID });
    let screenShareId = USER_ID + 'ScreenShare';
    if (document.getElementById(screenShareId)) {
        document.getElementById(screenShareId).remove();
    }
    restoreLayoutAfterScreenShare();
}

socketWrapper.on('screen-share-off', (userId) => {
    let screenShareId = userId + 'ScreenShare';
    UserScreenShareOn[userId] = 0;
    if (document.getElementById(screenShareId)) {
        document.getElementById(screenShareId).remove();
    }
    restoreLayoutAfterScreenShare();
});

function restoreLayoutAfterScreenShare() {
    if (layoutBeforeScreenShare !== null) {
        const restoreTo = layoutBeforeScreenShare;
        layoutBeforeScreenShare = null;
        switchLayout(restoreTo);
    }
    // After restore, ensure a valid video is pinned in spotlight/sidebar
    if ((currentLayout === 'spotlight' || currentLayout === 'sidebar') &&
        (!pinnedVideoId || !document.getElementById(pinnedVideoId))) {
        const firstVideo = document.querySelector('#video-area .innervideo');
        if (firstVideo) {
            pinVideo(firstVideo.id);
        } else {
            pinnedVideoId = null;
        }
    }
}

// Get display name for a user
function getDisplayName(userId, includeRole = false) {
    let name = '';

    // Check if we have a stored username for this user
    if (UserIdName[userId]) {
        name = UserIdName[userId];
    } else if (userId === USER_ID) {
        name = username;
    } else if (userId.startsWith('guest_')) {
        name = 'Guest_' + userId.slice(-4);
    } else {
        name = userId.substring(0, 8) + '...';
    }

    // Add role indicators
    if (userId === USER_ID) {
        if (IS_MODERATOR) {
            name += ' (Host)';
        } else {
            name += ' (You)';
        }
    }

    return name;
}

// Update video label when we learn a user's name
function updateVideoLabel(userId) {
    const videoDiv = document.getElementById(userId);
    if (videoDiv) {
        const label = videoDiv.querySelector('p');
        if (label) {
            label.textContent = getDisplayName(userId);
        }
    }
}

// Add Video Stream
async function addVideoStream(stream, userId, isScreenShare) {
    if (!stream) return;

    if (isScreenShare) {
        if (UserScreenShareOn[userId]) return;
        UserScreenShareOn[userId] = 1;

        const myVideo = document.createElement('video');
        const newVideodiv = document.createElement('div');
        const foot = document.createElement('p');
        foot.textContent = getDisplayName(userId) + ' (Screen)';
        newVideodiv.setAttribute('id', userId + 'ScreenShare');
        newVideodiv.setAttribute('class', 'innervideo');

        if (userId === USER_ID) {
            VideoDetails.myScreenShare = myVideo;
        }

        myVideo.srcObject = stream;
        myVideo.addEventListener('loadedmetadata', () => {
            myVideo.play();
            newVideodiv.append(myVideo);
            newVideodiv.append(foot);
            videoElement.append(newVideodiv);
        });
    } else {
        if (UserVideoOn[userId]) return;
        UserVideoOn[userId] = 1;

        const myVideo = document.createElement('video');
        const newVideodiv = document.createElement('div');
        const foot = document.createElement('p');
        const rawName = userId === USER_ID ? username : (UserIdName[userId] || userId.substring(0, 8));
        const displayName = userId === USER_ID ? username + ' (You)' : getDisplayName(userId);
        foot.textContent = displayName;
        newVideodiv.setAttribute('id', userId);
        newVideodiv.setAttribute('class', 'innervideo');

        // Avatar placeholder (shown when camera is off)
        const avatarDiv = document.createElement('div');
        avatarDiv.className = 'video-placeholder';
        const avatarCircle = document.createElement('div');
        avatarCircle.className = 'video-placeholder-avatar';
        avatarCircle.textContent = rawName.charAt(0).toUpperCase();
        avatarDiv.appendChild(avatarCircle);

        if (userId === USER_ID) {
            VideoDetails.myVideo = myVideo;
        }

        myVideo.muted = (userId === USER_ID);
        myVideo.srcObject = stream;
        myVideo.addEventListener('loadedmetadata', () => {
            myVideo.play();
            newVideodiv.append(avatarDiv);
            newVideodiv.append(myVideo);
            newVideodiv.append(foot);
            videoElement.append(newVideodiv);

            // Update label after a delay in case name info arrives later
            if (userId !== USER_ID) {
                setTimeout(() => {
                    updateVideoLabel(userId);
                    // Also update avatar initial
                    const name = UserIdName[userId] || rawName;
                    avatarCircle.textContent = name.charAt(0).toUpperCase();
                }, 1500);
            }
        });

        // Add audio to recording if active
        if (RecordingDetails.isRecording && stream) {
            addAudioSourceToMix(userId, stream);
        }
    }
}

// ================== RECORDING FEATURE ==================

function initializeRecordingCanvas() {
    RecordingDetails.recordingCanvas = document.createElement('canvas');
    RecordingDetails.recordingCanvas.width = 1280;
    RecordingDetails.recordingCanvas.height = 720;
    RecordingDetails.canvasContext = RecordingDetails.recordingCanvas.getContext('2d');
    RecordingDetails.canvasContext.fillStyle = '#1a1a2e';
    RecordingDetails.canvasContext.fillRect(0, 0, 1280, 720);
}

function drawVideosToCanvas(timestamp) {
    if (!RecordingDetails.isRecording) return;

    // Throttle to ~30fps
    if (!RecordingDetails._lastDrawTime) RecordingDetails._lastDrawTime = 0;
    if (timestamp && timestamp - RecordingDetails._lastDrawTime < 33) {
        RecordingDetails.animationFrameId = requestAnimationFrame(drawVideosToCanvas);
        return;
    }
    RecordingDetails._lastDrawTime = timestamp;

    const ctx = RecordingDetails.canvasContext;
    const canvas = RecordingDetails.recordingCanvas;

    ctx.fillStyle = '#1a1a2e';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    const videoArea = document.getElementById('video-area');
    const videoElements = videoArea ? videoArea.querySelectorAll('video') : [];
    const videoCount = videoElements.length;

    if (videoCount === 0) {
        ctx.fillStyle = '#ffffff';
        ctx.font = '24px Arial';
        ctx.textAlign = 'center';
        ctx.fillText('Waiting for participants...', canvas.width / 2, canvas.height / 2);
        RecordingDetails.animationFrameId = requestAnimationFrame(drawVideosToCanvas);
        return;
    }

    const cols = Math.ceil(Math.sqrt(videoCount));
    const rows = Math.ceil(videoCount / cols);
    const cellWidth = canvas.width / cols;
    const cellHeight = canvas.height / rows;

    videoElements.forEach((video, index) => {
        if (video.readyState >= 2) {
            const col = index % cols;
            const row = Math.floor(index / cols);
            const x = col * cellWidth;
            const y = row * cellHeight;

            const videoAspect = video.videoWidth / video.videoHeight;
            const cellAspect = cellWidth / cellHeight;

            let drawWidth, drawHeight, drawX, drawY;

            if (videoAspect > cellAspect) {
                drawWidth = cellWidth - 10;
                drawHeight = drawWidth / videoAspect;
                drawX = x + 5;
                drawY = y + (cellHeight - drawHeight) / 2;
            } else {
                drawHeight = cellHeight - 10;
                drawWidth = drawHeight * videoAspect;
                drawX = x + (cellWidth - drawWidth) / 2;
                drawY = y + 5;
            }

            ctx.drawImage(video, drawX, drawY, drawWidth, drawHeight);
            ctx.strokeStyle = '#4a4a6a';
            ctx.lineWidth = 2;
            ctx.strokeRect(drawX, drawY, drawWidth, drawHeight);
        }
    });

    // Timestamp
    ctx.fillStyle = 'rgba(255, 0, 0, 0.8)';
    ctx.fillRect(10, 10, 120, 30);
    ctx.fillStyle = '#ffffff';
    ctx.font = '14px Arial';
    ctx.textAlign = 'left';
    ctx.fillText('REC ' + new Date().toLocaleTimeString(), 20, 30);

    RecordingDetails.animationFrameId = requestAnimationFrame(drawVideosToCanvas);
}

function initializeAudioMixing() {
    RecordingDetails.audioContext = new (window.AudioContext || window.webkitAudioContext)();
    RecordingDetails.audioDestination = RecordingDetails.audioContext.createMediaStreamDestination();
    RecordingDetails.audioSources = {};
}

function addAudioSourceToMix(userId, stream) {
    if (!RecordingDetails.audioContext || !stream) return;

    try {
        const audioTracks = stream.getAudioTracks();
        if (audioTracks.length > 0) {
            const source = RecordingDetails.audioContext.createMediaStreamSource(stream);
            source.connect(RecordingDetails.audioDestination);
            RecordingDetails.audioSources[userId] = source;
        }
    } catch (err) {
        console.error('Error adding audio source:', err);
    }
}

function removeAudioSourceFromMix(userId) {
    if (RecordingDetails.audioSources[userId]) {
        try {
            RecordingDetails.audioSources[userId].disconnect();
            delete RecordingDetails.audioSources[userId];
        } catch (err) {
            console.error('Error removing audio source:', err);
        }
    }
}

async function startRecording() {
    try {
        initializeRecordingCanvas();
        initializeAudioMixing();

        if (VideoDetails.myVideoStream) {
            addAudioSourceToMix(USER_ID, VideoDetails.myVideoStream);
        }

        Object.keys(UserStreamwithId).forEach(userId => {
            if (UserStreamwithId[userId]) {
                addAudioSourceToMix(userId, UserStreamwithId[userId]);
            }
        });

        const canvasStream = RecordingDetails.recordingCanvas.captureStream(30);
        const combinedStream = new MediaStream();

        canvasStream.getVideoTracks().forEach(track => combinedStream.addTrack(track));
        RecordingDetails.audioDestination.stream.getAudioTracks().forEach(track => combinedStream.addTrack(track));

        const mimeTypes = ['video/webm;codecs=vp9,opus', 'video/webm;codecs=vp8,opus', 'video/webm'];
        let selectedMimeType = mimeTypes.find(type => MediaRecorder.isTypeSupported(type)) || 'video/webm';

        RecordingDetails.mediaRecorder = new MediaRecorder(combinedStream, { mimeType: selectedMimeType });
        RecordingDetails.recordedChunks = [];

        RecordingDetails.mediaRecorder.ondataavailable = (event) => {
            if (event.data.size > 0) {
                RecordingDetails.recordedChunks.push(event.data);
            }
        };

        RecordingDetails.mediaRecorder.onstop = () => {
            const blob = new Blob(RecordingDetails.recordedChunks, { type: 'video/webm' });
            const duration = RecordingDetails.startTime
                ? Math.round((Date.now() - RecordingDetails.startTime) / 1000)
                : 0;

            if (typeof RECORDING_TO_S3 !== 'undefined' && RECORDING_TO_S3) {
                // Upload to S3 via server
                uploadRecordingToS3(blob, duration);
            } else {
                // Download locally
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `meeting-recording-${Date.now()}.webm`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
            }
        };

        RecordingDetails.mediaRecorder.start(1000);
        RecordingDetails.isRecording = true;
        RecordingDetails.startTime = Date.now();

        drawVideosToCanvas();

        document.getElementById('recordButton').classList.add('recording');
        document.getElementById('recording-indicator').style.display = 'flex';
        socketWrapper.emit('recording-started', { user_id: USER_ID });

    } catch (err) {
        console.error('Error starting recording:', err);
        alert('Failed to start recording: ' + err.message);
    }
}

function stopRecording() {
    if (!RecordingDetails.isRecording) return;

    try {
        if (RecordingDetails.mediaRecorder && RecordingDetails.mediaRecorder.state !== 'inactive') {
            RecordingDetails.mediaRecorder.stop();
        }

        if (RecordingDetails.animationFrameId) {
            cancelAnimationFrame(RecordingDetails.animationFrameId);
            RecordingDetails.animationFrameId = null;
        }

        Object.keys(RecordingDetails.audioSources).forEach(userId => {
            removeAudioSourceFromMix(userId);
        });

        if (RecordingDetails.audioContext) {
            RecordingDetails.audioContext.close();
            RecordingDetails.audioContext = null;
        }

        RecordingDetails.isRecording = false;

        document.getElementById('recordButton').classList.remove('recording');
        document.getElementById('recording-indicator').style.display = 'none';
        socketWrapper.emit('recording-stopped', { user_id: USER_ID });

    } catch (err) {
        console.error('Error stopping recording:', err);
    }
}

// Record button handler (only for moderators)
const recordButton = document.getElementById('recordButton');
if (recordButton) {
    recordButton.addEventListener('click', () => {
        if (!RecordingDetails.isRecording) {
            startRecording();
        } else {
            stopRecording();
        }
    });
}

socketWrapper.on('recording-started', (userId) => {
    document.getElementById('recording-indicator').style.display = 'flex';
});

socketWrapper.on('recording-stopped', (userId) => {
    if (!RecordingDetails.isRecording) {
        document.getElementById('recording-indicator').style.display = 'none';
    }
});

// Host approval alerts are now handled inside connectUserSocket()

// Show a nice modal for join requests instead of confirm()
function showJoinRequestModal(userId, username, roomId) {
    // Remove any existing modal
    const existingModal = document.getElementById('join-request-modal');
    if (existingModal) existingModal.remove();

    const modal = document.createElement('div');
    modal.id = 'join-request-modal';
    modal.className = 'join-request-modal';
    modal.innerHTML = `
        <div class="join-request-content">
            <div class="join-request-header">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
                    <circle cx="9" cy="7" r="4"/>
                    <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
                    <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
                </svg>
                <h3>Someone wants to join</h3>
            </div>
            <p><strong class="join-request-username"></strong> is asking to join this meeting.</p>
            <div class="join-request-actions">
                <button class="btn-deny">Deny</button>
                <button class="btn-admit">Admit</button>
            </div>
        </div>
    `;

    // Set username safely via textContent (prevents XSS)
    modal.querySelector('.join-request-username').textContent = username || 'A user';

    // Attach event listeners instead of inline onclick (prevents script injection via userId)
    modal.querySelector('.btn-deny').addEventListener('click', function() {
        respondToJoinRequest(userId, false);
    });
    modal.querySelector('.btn-admit').addEventListener('click', function() {
        respondToJoinRequest(userId, true);
    });

    document.body.appendChild(modal);

    // Auto-dismiss after 30 seconds
    setTimeout(() => {
        if (document.getElementById('join-request-modal')) {
            respondToJoinRequest(userId, false);
        }
    }, 30000);
}

function respondToJoinRequest(userId, approved) {
    // Remove modal
    const modal = document.getElementById('join-request-modal');
    if (modal) modal.remove();

    // Send response via room socket
    socketWrapper.emit('alert-response', {
        approved: approved,
        requesting_user_id: userId
    });

    // Show notification
    if (approved) {
        showNotification(`User admitted to meeting`);
    } else {
        showNotification(`Join request denied`);
    }
}

// ================== MODERATOR CONTROLS ==================

// Make socket available globally for moderator controls
window.socket = socket;

// Track participants with their info
let ParticipantsInfo = {};
ParticipantsInfo[USER_ID] = { id: USER_ID, username: username };

// Update participants info when new user joins
socketWrapper.on('participant-info', (data) => {
    if (data.user_id && data.username) {
        ParticipantsInfo[data.user_id] = { id: data.user_id, username: data.username };
        updateParticipantsPanel();
    }
});

// Update when user disconnects
socketWrapper.on('user-disconnected', (userId) => {
    delete ParticipantsInfo[userId];
    updateParticipantsPanel();
});

// Handle mute-all from moderator
socketWrapper.on('mute-all', (data) => {
    // Mute my own microphone
    if (VideoDetails.myVideoStream) {
        const audioTracks = VideoDetails.myVideoStream.getAudioTracks();
        audioTracks.forEach(track => {
            track.enabled = false;
        });
        micEnabled = false;
        micButton.classList.add('muted');
        micButton.title = 'Unmute Microphone (M)';
        socketWrapper.emit('mute-status', { room_id: ROOM_ID, user_id: USER_ID, is_muted: true });
        updateMuteIndicator(USER_ID, true);
        showMuteNotification('You have been muted by the moderator');
    }
});

// Handle being kicked from meeting
socketWrapper.on('kicked', (data) => {
    showKickedOverlay();
});

// Handle kick confirmation for moderator
socketWrapper.on('user-kicked', (data) => {
    if (data.targetUserId) {
        delete ParticipantsInfo[data.targetUserId];
        updateParticipantsPanel();
    }
});

function updateParticipantsPanel() {
    const participants = Object.values(ParticipantsInfo);
    if (typeof updateParticipantsList === 'function') {
        updateParticipantsList(participants);
    }

    // Also update participant count
    const count = participants.length;
    const countElement = document.getElementById('participant-count');
    if (countElement) {
        countElement.textContent = count;
    }
}

function showMuteNotification(message) {
    const notification = document.createElement('div');
    notification.className = 'moderator-notification';
    notification.innerHTML = `
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right: 8px;">
            <line x1="1" y1="1" x2="23" y2="23"/>
            <path d="M9 9v3a3 3 0 0 0 5.12 2.12M15 9.34V4a3 3 0 0 0-5.94-.6"/>
            <path d="M17 16.95A7 7 0 0 1 5 12v-2m14 0v2a7 7 0 0 1-.11 1.23"/>
        </svg>
        ${message}
    `;
    document.body.appendChild(notification);
    setTimeout(() => {
        notification.classList.add('fade-out');
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

function showKickedOverlay() {
    // Stop all media
    if (VideoDetails.myVideoStream) {
        VideoDetails.myVideoStream.getTracks().forEach(track => track.stop());
    }
    if (VideoDetails.myScreenStream) {
        VideoDetails.myScreenStream.getTracks().forEach(track => track.stop());
    }

    // Close peer connections
    if (myPeer) myPeer.destroy();
    if (myPeer2) myPeer2.destroy();

    // Show kicked message
    const overlay = document.createElement('div');
    overlay.className = 'kicked-overlay';
    overlay.innerHTML = `
        <svg width="80" height="80" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2" style="margin-bottom: 20px;">
            <circle cx="12" cy="12" r="10"/>
            <line x1="15" y1="9" x2="9" y2="15"/>
            <line x1="9" y1="9" x2="15" y2="15"/>
        </svg>
        <h2>You have been removed from this meeting</h2>
        <p>The moderator has removed you from this meeting.</p>
        <a href="/">Return to Home</a>
    `;
    document.body.appendChild(overlay);
}

// Share participant info is handled inside connectRoomSocket() onopen

// Listen for info requests
socketWrapper.on('request-info', () => {
    socketWrapper.emit('share-info', {
        user_id: USER_ID,
        username: username,
        is_moderator: IS_MODERATOR
    });
});

// Track who is the room moderator/host
let RoomModerators = {};

// Receive other participants info
socketWrapper.on('share-info', (data) => {
    if (data.user_id && data.username) {
        const displayName = data.is_moderator ? data.username + ' (Host)' : data.username;
        ParticipantsInfo[data.user_id] = {
            id: data.user_id,
            username: data.username,
            is_moderator: data.is_moderator
        };
        UserIdName[data.user_id] = displayName;
        if (data.is_moderator) {
            RoomModerators[data.user_id] = true;
        }
        updateParticipantsPanel();
        // Update video label if video already exists
        updateVideoLabel(data.user_id);
    }
});

// Initialize participants panel on load
document.addEventListener('DOMContentLoaded', () => {
    updateParticipantsPanel();
});

// ================== SCREENSHOT FEATURE ==================

const screenshotBtn = document.getElementById('screenshotBtn');
if (screenshotBtn) {
    screenshotBtn.addEventListener('click', takeScreenshot);
}

async function takeScreenshot() {
    try {
        // Create flash effect
        const flash = document.createElement('div');
        flash.className = 'screenshot-flash';
        document.body.appendChild(flash);
        setTimeout(() => flash.remove(), 300);

        // Create canvas to capture meeting view
        const canvas = document.createElement('canvas');
        const ctx = canvas.getContext('2d');

        // Set canvas size
        canvas.width = 1920;
        canvas.height = 1080;

        // Fill background
        ctx.fillStyle = '#0f0f0f';
        ctx.fillRect(0, 0, canvas.width, canvas.height);

        // Get all video elements
        const videoArea = document.getElementById('video-area');
        const videoElements = videoArea.querySelectorAll('video');
        const videoCount = videoElements.length;

        if (videoCount === 0) {
            showScreenshotNotification('No videos to capture', true);
            return;
        }

        // Calculate grid layout
        const cols = Math.ceil(Math.sqrt(videoCount));
        const rows = Math.ceil(videoCount / cols);
        const cellWidth = canvas.width / cols;
        const cellHeight = canvas.height / rows;
        const padding = 10;

        // Draw each video to canvas
        let index = 0;
        for (const video of videoElements) {
            if (video.readyState >= 2) {
                const col = index % cols;
                const row = Math.floor(index / cols);
                const x = col * cellWidth + padding;
                const y = row * cellHeight + padding;
                const w = cellWidth - padding * 2;
                const h = cellHeight - padding * 2;

                // Calculate aspect ratio fit
                const videoAspect = video.videoWidth / video.videoHeight;
                const cellAspect = w / h;

                let drawWidth, drawHeight, drawX, drawY;

                if (videoAspect > cellAspect) {
                    drawWidth = w;
                    drawHeight = w / videoAspect;
                    drawX = x;
                    drawY = y + (h - drawHeight) / 2;
                } else {
                    drawHeight = h;
                    drawWidth = h * videoAspect;
                    drawX = x + (w - drawWidth) / 2;
                    drawY = y;
                }

                // Draw rounded rectangle background
                ctx.fillStyle = '#1a1a1a';
                roundRect(ctx, x, y, w, h, 12, true, false);

                // Draw video
                ctx.save();
                roundRect(ctx, drawX, drawY, drawWidth, drawHeight, 8, false, false);
                ctx.clip();
                ctx.drawImage(video, drawX, drawY, drawWidth, drawHeight);
                ctx.restore();

                // Draw participant name
                const videoDiv = video.parentElement;
                const nameLabel = videoDiv.querySelector('p');
                if (nameLabel) {
                    ctx.fillStyle = 'rgba(0, 0, 0, 0.7)';
                    ctx.fillRect(x, y + h - 35, w, 35);
                    ctx.fillStyle = 'white';
                    ctx.font = '14px Inter, sans-serif';
                    ctx.fillText(nameLabel.textContent, x + 12, y + h - 12);
                }
            }
            index++;
        }

        // Add watermark
        ctx.fillStyle = 'rgba(255, 255, 255, 0.5)';
        ctx.font = '16px Inter, sans-serif';
        ctx.textAlign = 'right';
        const timestamp = new Date().toLocaleString();
        ctx.fillText(`PyTalk Meeting - ${timestamp}`, canvas.width - 20, canvas.height - 20);

        // Download the screenshot
        const link = document.createElement('a');
        link.download = `pytalk-meeting-${Date.now()}.png`;
        link.href = canvas.toDataURL('image/png');
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);

        showScreenshotNotification('Screenshot saved!');

    } catch (err) {
        console.error('Error taking screenshot:', err);
        showScreenshotNotification('Failed to take screenshot', true);
    }
}

function roundRect(ctx, x, y, width, height, radius, fill, stroke) {
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.lineTo(x + width - radius, y);
    ctx.quadraticCurveTo(x + width, y, x + width, y + radius);
    ctx.lineTo(x + width, y + height - radius);
    ctx.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
    ctx.lineTo(x + radius, y + height);
    ctx.quadraticCurveTo(x, y + height, x, y + height - radius);
    ctx.lineTo(x, y + radius);
    ctx.quadraticCurveTo(x, y, x + radius, y);
    ctx.closePath();
    if (fill) ctx.fill();
    if (stroke) ctx.stroke();
}

function showScreenshotNotification(message, isError = false) {
    const notification = document.createElement('div');
    notification.className = 'screenshot-notification';
    if (isError) {
        notification.style.background = 'var(--danger)';
    }
    notification.innerHTML = `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            ${isError
                ? '<circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>'
                : '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>'
            }
        </svg>
        ${message}
    `;
    document.body.appendChild(notification);
    setTimeout(() => {
        notification.style.opacity = '0';
        notification.style.transform = 'translateX(-50%) translateY(10px)';
        setTimeout(() => notification.remove(), 300);
    }, 2500);
}

// ================== LAYOUT FEATURE ==================

const layoutBtn = document.getElementById('layoutBtn');
const layoutPicker = document.getElementById('layoutPicker');
const layoutModes = ['grid', 'spotlight', 'sidebar'];

if (layoutBtn) {
    layoutBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        if (layoutPicker) layoutPicker.classList.toggle('open');
    });
}

// Close picker when clicking outside
document.addEventListener('click', function(e) {
    if (layoutPicker && !layoutPicker.contains(e.target) && e.target !== layoutBtn) {
        layoutPicker.classList.remove('open');
    }
});

// Handle picker option clicks
if (layoutPicker) {
    layoutPicker.querySelectorAll('.layout-picker-option').forEach(function(opt) {
        opt.addEventListener('click', function() {
            switchLayout(this.dataset.layout);
            layoutPicker.classList.remove('open');
        });
    });
}

function switchLayout(mode) {
    if (mode === currentLayout) return;

    const videoArea = document.getElementById('video-area');
    const prevLayout = currentLayout;

    // --- Exit previous layout ---
    exitLayout(videoArea, prevLayout);

    // --- Enter new layout ---
    currentLayout = mode;
    if (layoutBtn) layoutBtn.setAttribute('data-layout', mode);

    // Update picker active state
    if (layoutPicker) {
        layoutPicker.querySelectorAll('.layout-picker-option').forEach(function(opt) {
            opt.classList.toggle('active', opt.dataset.layout === mode);
        });
    }

    if (mode === 'grid') {
        if (layoutBtn) layoutBtn.title = 'Change Layout (L)';
        showNotification('Grid layout');
    } else if (mode === 'spotlight') {
        videoArea.classList.add('spotlight-layout');
        if (layoutBtn) layoutBtn.title = 'Change Layout (L)';
        enterPinnedLayout(videoArea, 'thumbnails-row');
        setupPinHandlers();
        showNotification('Spotlight layout - Click a video to pin');
    } else if (mode === 'sidebar') {
        videoArea.classList.add('sidebar-layout');
        if (layoutBtn) layoutBtn.title = 'Change Layout (L)';
        enterPinnedLayout(videoArea, 'sidebar-column');
        setupPinHandlers();
        showNotification('Sidebar layout - Click a video to pin');
    }
}

function exitLayout(videoArea, layout) {
    if (layout === 'spotlight' || layout === 'sidebar') {
        unpinAllVideos();

        // Move videos out of container row back to main area
        const containerClass = layout === 'spotlight' ? 'thumbnails-row' : 'sidebar-column';
        const container = videoArea.querySelector('.' + containerClass);
        if (container) {
            while (container.firstChild) {
                videoArea.appendChild(container.firstChild);
            }
            container.remove();
        }
    }
    videoArea.classList.remove('spotlight-layout', 'sidebar-layout');
}

function enterPinnedLayout(videoArea, containerClass) {
    // Pin the first video by default
    const firstVideo = videoArea.querySelector('.innervideo');
    if (firstVideo) {
        pinVideo(firstVideo.id, containerClass);
    }
}

function cycleLayout() {
    const idx = layoutModes.indexOf(currentLayout);
    const next = layoutModes[(idx + 1) % layoutModes.length];
    switchLayout(next);
}

function pinVideo(videoId, containerClass) {
    const videoArea = document.getElementById('video-area');
    const allVideos = videoArea.querySelectorAll('.innervideo');

    // Unpin all first
    allVideos.forEach(v => {
        v.classList.remove('pinned');
        const indicator = v.querySelector('.pin-indicator');
        if (indicator) indicator.remove();
    });

    // Pin the selected video
    const videoDiv = document.getElementById(videoId);
    if (videoDiv) {
        videoDiv.classList.add('pinned');
        pinnedVideoId = videoId;

        // Add pin indicator
        if (!videoDiv.querySelector('.pin-indicator')) {
            const indicator = document.createElement('div');
            indicator.className = 'pin-indicator';
            indicator.innerHTML = `
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M12 17v5"/>
                    <path d="M9 11l3-3 3 3"/>
                    <rect x="6" y="3" width="12" height="8" rx="1"/>
                </svg>
                Pinned
            `;
            videoDiv.appendChild(indicator);
        }

        // Reorganize layout
        reorganizePinnedLayout(containerClass);
    }
}

function unpinAllVideos() {
    const videoArea = document.getElementById('video-area');
    const allVideos = videoArea.querySelectorAll('.innervideo');

    allVideos.forEach(v => {
        v.classList.remove('pinned');
        const indicator = v.querySelector('.pin-indicator');
        if (indicator) indicator.remove();
    });

    pinnedVideoId = null;
}

function reorganizePinnedLayout(containerClass) {
    const videoArea = document.getElementById('video-area');
    const isSpotlight = videoArea.classList.contains('spotlight-layout');
    const isSidebar = videoArea.classList.contains('sidebar-layout');
    if (!isSpotlight && !isSidebar) return;

    // Determine the container class name
    const cls = containerClass || (isSpotlight ? 'thumbnails-row' : 'sidebar-column');

    const pinnedVideo = videoArea.querySelector('.innervideo.pinned');
    const otherVideos = videoArea.querySelectorAll('.innervideo:not(.pinned)');

    // Create or get container
    let container = videoArea.querySelector('.' + cls);
    if (!container && otherVideos.length > 0) {
        container = document.createElement('div');
        container.className = cls;
        videoArea.appendChild(container);
    }

    // Move pinned video to main area
    if (pinnedVideo) {
        videoArea.insertBefore(pinnedVideo, container);
    }

    // Move other videos to container
    if (container) {
        otherVideos.forEach(v => {
            container.appendChild(v);
        });
    }
}

let pinHandlersAttached = false;
function setupPinHandlers() {
    if (pinHandlersAttached) return;
    const videoArea = document.getElementById('video-area');

    // Add click handler to video area (event delegation)
    videoArea.addEventListener('click', handleVideoClick);
    pinHandlersAttached = true;
}

function handleVideoClick(e) {
    if (currentLayout !== 'spotlight' && currentLayout !== 'sidebar') return;

    // Find the clicked video div
    const videoDiv = e.target.closest('.innervideo');
    if (videoDiv && !videoDiv.classList.contains('pinned')) {
        pinVideo(videoDiv.id);
    }
}

// Override addVideoStream to handle layout for new streams
const originalAddVideoStream = addVideoStream;
addVideoStream = async function(stream, userId, isScreenShare) {
    await originalAddVideoStream(stream, userId, isScreenShare);

    if (isScreenShare) {
        // Auto-spotlight the screen share for all participants
        setTimeout(() => {
            const screenShareId = userId + 'ScreenShare';
            const screenShareEl = document.getElementById(screenShareId);
            if (!screenShareEl) return;

            // Save current layout so we can restore when screen share ends
            if (layoutBeforeScreenShare === null) {
                layoutBeforeScreenShare = currentLayout;
            }

            // Switch to spotlight if in grid
            if (currentLayout === 'grid') {
                switchLayout('spotlight');
            }

            // Pin the screen share as the main video
            pinVideo(screenShareId);
        }, 200);
    } else if (currentLayout === 'spotlight' || currentLayout === 'sidebar') {
        // Regular video — reorganize pinned layout
        setTimeout(() => {
            if (!pinnedVideoId) {
                const firstVideo = document.querySelector('#video-area .innervideo');
                if (firstVideo) {
                    pinVideo(firstVideo.id);
                }
            } else {
                reorganizePinnedLayout();
            }
        }, 100);
    }
};

// ================== END MEETING ==================

function showEndMeetingModal() {
    // Remove any existing modal
    const existingModal = document.getElementById('end-meeting-modal');
    if (existingModal) existingModal.remove();

    const modal = document.createElement('div');
    modal.id = 'end-meeting-modal';
    modal.className = 'join-request-modal';
    modal.innerHTML = `
        <div class="join-request-content">
            <div class="join-request-header">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M10.68 13.31a16 16 0 0 0 3.41 2.6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7 2 2 0 0 1 1.72 2v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.42 19.42 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.63A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91"/>
                    <line x1="23" y1="1" x2="1" y2="23"/>
                </svg>
                <h3>End Meeting</h3>
            </div>
            <p>Are you sure you want to end this meeting for <strong>all participants</strong>?</p>
            <div class="join-request-actions">
                <button class="btn-deny" onclick="closeEndMeetingModal()">Cancel</button>
                <button class="btn-admit btn-end-meeting" onclick="confirmEndMeeting()">End Meeting</button>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
}

function closeEndMeetingModal() {
    const modal = document.getElementById('end-meeting-modal');
    if (modal) modal.remove();
}

function confirmEndMeeting() {
    closeEndMeetingModal();
    // Send end-meeting event to all participants
    socketWrapper.emit('end-meeting', {
        room_id: ROOM_ID,
        moderator_id: USER_ID
    });
    // Clean up and redirect
    cleanupAndLeave();
}

function endMeeting() {
    if (IS_MODERATOR) {
        // Show custom confirmation modal for moderator
        showEndMeetingModal();
    } else {
        // Participant just leaves
        cleanupAndLeave();
    }
}

function cleanupAndLeave() {
    // Stop all media tracks
    if (VideoDetails.myVideoStream) {
        VideoDetails.myVideoStream.getTracks().forEach(track => track.stop());
    }
    if (VideoDetails.myScreenStream) {
        VideoDetails.myScreenStream.getTracks().forEach(track => track.stop());
    }

    // Stop recording if active
    if (RecordingDetails.isRecording) {
        stopRecording();
    }

    // Close peer connections
    if (myPeer) myPeer.destroy();
    if (myPeer2) myPeer2.destroy();

    // Prevent reconnection attempts after intentional leave
    roomReconnectAttempts = WS_MAX_RECONNECT_ATTEMPTS;
    userReconnectAttempts = WS_MAX_RECONNECT_ATTEMPTS;
    if (roomReconnectTimer) { clearTimeout(roomReconnectTimer); roomReconnectTimer = null; }
    if (userReconnectTimer) { clearTimeout(userReconnectTimer); userReconnectTimer = null; }
    if (roomHeartbeat) roomHeartbeat.stop();
    if (userHeartbeat) userHeartbeat.stop();

    // Close WebSocket connections
    if (socket) socket.close();
    if (userSocket) userSocket.close();

    // Redirect to home
    window.location.href = '/';
}

// Handle meeting ended by moderator
socketWrapper.on('meeting-ended', (data) => {
    showMeetingEndedOverlay();
});

// Duration limit events
socketWrapper.on('duration-warning', (data) => {
    var mins = data.minutes_remaining || 5;
    var toast = document.createElement('div');
    toast.className = 'alert alert-warning';
    toast.style.cssText = 'position:fixed;top:80px;left:50%;transform:translateX(-50%);z-index:10000;padding:12px 24px;border-radius:8px;font-weight:600;animation:fadeIn 0.3s;';
    toast.textContent = 'Meeting ends in ' + mins + ' minute(s). Upgrade your plan for unlimited meetings.';
    document.body.appendChild(toast);
    setTimeout(function() { toast.remove(); }, 15000);
});

socketWrapper.on('meeting-duration-exceeded', (data) => {
    // Stop all media
    if (VideoDetails.myVideoStream) {
        VideoDetails.myVideoStream.getTracks().forEach(function(track) { track.stop(); });
    }
    if (VideoDetails.myScreenStream) {
        VideoDetails.myScreenStream.getTracks().forEach(function(track) { track.stop(); });
    }
    if (myPeer) myPeer.destroy();
    if (myPeer2) myPeer2.destroy();

    var overlay = document.createElement('div');
    overlay.className = 'kicked-overlay';
    overlay.innerHTML = '<svg width="80" height="80" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2" style="margin-bottom:20px;"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>' +
        '<h2>Meeting Duration Limit Reached</h2>' +
        '<p>' + (data.message || 'Your plan has a 30-minute meeting limit.') + '</p>' +
        '<p>Upgrade to Pro or Business for unlimited meetings.</p>' +
        '<a href="/billing/pricing/">View Plans</a>&nbsp;&nbsp;' +
        '<a href="/">Return to Home</a>';
    document.body.appendChild(overlay);
});

function showMeetingEndedOverlay() {
    // Stop all media
    if (VideoDetails.myVideoStream) {
        VideoDetails.myVideoStream.getTracks().forEach(track => track.stop());
    }
    if (VideoDetails.myScreenStream) {
        VideoDetails.myScreenStream.getTracks().forEach(track => track.stop());
    }

    // Close peer connections
    if (myPeer) myPeer.destroy();
    if (myPeer2) myPeer2.destroy();

    // Show meeting ended message
    const overlay = document.createElement('div');
    overlay.className = 'kicked-overlay';
    overlay.innerHTML = `
        <svg width="80" height="80" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2" style="margin-bottom: 20px;">
            <path d="M10.68 13.31a16 16 0 0 0 3.41 2.6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7 2 2 0 0 1 1.72 2v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.42 19.42 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.63A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 2.59 3.4z"/>
        </svg>
        <h2>Meeting Ended</h2>
        <p>The host has ended this meeting.</p>
        <a href="/">Return to Home</a>
    `;
    document.body.appendChild(overlay);
}

// ================== KEYBOARD SHORTCUTS ==================

document.addEventListener('keydown', (e) => {
    // Don't trigger shortcuts when typing in chat
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

    switch (e.key.toLowerCase()) {
        case 's':
            // Ctrl/Cmd + S for screenshot
            if (e.ctrlKey || e.metaKey) {
                e.preventDefault();
                takeScreenshot();
            }
            break;
        case 'l':
            // L for layout cycle
            if (!e.ctrlKey && !e.metaKey) {
                cycleLayout();
            }
            break;
        case 'm':
            // M for mute toggle
            if (!e.ctrlKey && !e.metaKey) {
                document.getElementById('mic')?.click();
            }
            break;
        case 'v':
            // V for video toggle
            if (!e.ctrlKey && !e.metaKey) {
                document.getElementById('onVideo')?.click();
            }
            break;
        case 'c':
            // C for chat toggle
            if (!e.ctrlKey && !e.metaKey) {
                toggleChat();
            }
            break;
        case 'b':
            // B for background effects
            if (!e.ctrlKey && !e.metaKey) {
                toggleBgEffectsPopup();
            }
            break;
        case 'escape':
            // Escape to close panels
            const sidebar = document.getElementById('sidebar');
            if (sidebar.classList.contains('active')) {
                sidebar.classList.remove('active');
            }
            const participantsPanel = document.getElementById('participants-panel');
            if (participantsPanel && participantsPanel.style.display !== 'none') {
                participantsPanel.style.display = 'none';
            }
            // Close bg effects popup
            const bgPopup = document.getElementById('bgEffectsPopup');
            if (bgPopup) bgPopup.classList.remove('open');
            break;
    }
});

// ================== S3 RECORDING UPLOAD ==================

async function uploadRecordingToS3(blob, duration) {
    // Show upload progress notification
    const notification = document.createElement('div');
    notification.id = 'upload-notification';
    notification.className = 'moderator-notification';
    notification.innerHTML = `
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right: 8px; animation: spin 1s linear infinite;">
            <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
        </svg>
        <span>Uploading recording...</span>
    `;
    notification.style.animation = 'none';
    notification.style.background = 'var(--accent, #6366f1)';
    document.body.appendChild(notification);

    try {
        const formData = new FormData();
        formData.append('recording', blob, `recording-${Date.now()}.webm`);
        formData.append('room_id', ROOM_ID);
        formData.append('duration', duration);

        const response = await fetch('/meeting/upload-recording/', {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCookie('csrftoken'),
            },
            body: formData,
        });

        const data = await response.json();

        // Remove progress notification
        notification.remove();

        if (data.success) {
            showNotification('Recording saved to cloud successfully!');
        } else {
            showNotification(data.error || 'Failed to upload recording');
            // Fallback: download locally
            downloadRecordingLocally(blob);
        }
    } catch (err) {
        console.error('Error uploading recording:', err);
        notification.remove();
        showNotification('Upload failed. Downloading locally instead.');
        downloadRecordingLocally(blob);
    }
}

function downloadRecordingLocally(blob) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `meeting-recording-${Date.now()}.webm`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

// ================== BACKGROUND EFFECTS ==================

let bgEffectState = {
    currentEffect: 'none',   // 'none', 'blur', 'image'
    segmenter: null,
    canvas: null,
    ctx: null,
    bgImage: null,
    bgGradient: null,
    animFrameId: null,
    originalStream: null,
    processedStream: null,
    isProcessing: false,
    streamSwapped: false,
};

// Toggle popup
function toggleBgEffectsPopup() {
    const popup = document.getElementById('bgEffectsPopup');
    if (popup) popup.classList.toggle('open');
}

// Setup popup event listeners
const bgEffectBtn = document.getElementById('bgEffectBtn');
if (bgEffectBtn) {
    bgEffectBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        toggleBgEffectsPopup();
    });
}

// Close popup when clicking outside
document.addEventListener('click', function(e) {
    const popup = document.getElementById('bgEffectsPopup');
    const btn = document.getElementById('bgEffectBtn');
    if (popup && !popup.contains(e.target) && e.target !== btn && !btn.contains(e.target)) {
        popup.classList.remove('open');
    }
});

// Handle effect option clicks
document.querySelectorAll('.bg-effect-option').forEach(function(opt) {
    opt.addEventListener('click', function() {
        const effect = this.dataset.effect;
        const presetsEl = document.getElementById('bgPresets');

        // Update active state
        document.querySelectorAll('.bg-effect-option').forEach(o => o.classList.remove('active'));
        this.classList.add('active');

        if (effect === 'image') {
            if (presetsEl) presetsEl.style.display = 'block';
        } else {
            if (presetsEl) presetsEl.style.display = 'none';
        }

        if (effect === 'none') {
            disableBgEffect();
        } else if (effect === 'blur') {
            enableBgEffect('blur');
        }
        // 'image' waits for preset/upload selection
    });
});

// Handle preset background clicks
document.querySelectorAll('.bg-preset-item').forEach(function(item) {
    item.addEventListener('click', function() {
        // Remove active from all presets
        document.querySelectorAll('.bg-preset-item').forEach(i => i.classList.remove('active'));
        this.classList.add('active');

        // Create gradient image from the preset
        const gradientCanvas = document.createElement('canvas');
        gradientCanvas.width = 640;
        gradientCanvas.height = 480;
        const gCtx = gradientCanvas.getContext('2d');

        const style = window.getComputedStyle(this);
        const bgStr = style.backgroundImage;

        // Parse gradient colors
        const gradients = {
            'gradient1': ['#667eea', '#764ba2'],
            'gradient2': ['#f093fb', '#f5576c'],
            'gradient3': ['#4facfe', '#00f2fe'],
            'gradient4': ['#43e97b', '#38f9d7'],
        };

        const colors = gradients[this.dataset.bg] || ['#667eea', '#764ba2'];
        const grad = gCtx.createLinearGradient(0, 0, 640, 480);
        grad.addColorStop(0, colors[0]);
        grad.addColorStop(1, colors[1]);
        gCtx.fillStyle = grad;
        gCtx.fillRect(0, 0, 640, 480);

        const img = new Image();
        img.src = gradientCanvas.toDataURL();
        img.onload = function() {
            bgEffectState.bgImage = img;
            enableBgEffect('image');
        };
    });
});

// Handle custom image upload
const bgImageUpload = document.getElementById('bgImageUpload');
if (bgImageUpload) {
    bgImageUpload.addEventListener('change', function(e) {
        const file = e.target.files[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = function(ev) {
            const img = new Image();
            img.src = ev.target.result;
            img.onload = function() {
                bgEffectState.bgImage = img;
                // Remove active from presets
                document.querySelectorAll('.bg-preset-item').forEach(i => i.classList.remove('active'));
                enableBgEffect('image');
            };
        };
        reader.readAsDataURL(file);
    });
}

async function initSegmenter() {
    if (bgEffectState.segmenter) return bgEffectState.segmenter;

    if (typeof SelfieSegmentation === 'undefined') {
        console.error('SelfieSegmentation class not found');
        showNotification('Background effects not available. MediaPipe not loaded.');
        return null;
    }

    try {
        const segmenter = new SelfieSegmentation({
            locateFile: (file) => `https://cdn.jsdelivr.net/npm/@mediapipe/selfie_segmentation@0.1.1675465747/${file}`
        });

        segmenter.setOptions({
            modelSelection: 1, // 1 = landscape (faster), 0 = general
        });

        segmenter.onResults(onSegmentationResults);

        // Force WASM/model initialization by sending a test frame
        const testCanvas = document.createElement('canvas');
        testCanvas.width = 64;
        testCanvas.height = 64;
        const testCtx = testCanvas.getContext('2d');
        testCtx.fillRect(0, 0, 64, 64);
        await segmenter.send({ image: testCanvas });

        console.log('MediaPipe SelfieSegmentation initialized successfully');
        bgEffectState.segmenter = segmenter;
        return segmenter;
    } catch (err) {
        console.error('Failed to initialize segmenter:', err);
        showNotification('Background effects failed to initialize. Check browser console.');
        return null;
    }
}

function onSegmentationResults(results) {
    if (!bgEffectState.ctx || !bgEffectState.canvas) return;

    const ctx = bgEffectState.ctx;
    const canvas = bgEffectState.canvas;
    const width = canvas.width;
    const height = canvas.height;

    ctx.save();
    ctx.clearRect(0, 0, width, height);

    // Draw the segmentation mask
    ctx.drawImage(results.segmentationMask, 0, 0, width, height);

    // Only draw the person (where mask is white)
    ctx.globalCompositeOperation = 'source-in';
    ctx.drawImage(results.image, 0, 0, width, height);

    // Draw background behind person
    ctx.globalCompositeOperation = 'destination-over';

    if (bgEffectState.currentEffect === 'blur') {
        // Draw blurred version of camera
        ctx.filter = 'blur(15px)';
        ctx.drawImage(results.image, 0, 0, width, height);
        ctx.filter = 'none';
    } else if (bgEffectState.currentEffect === 'image' && bgEffectState.bgImage) {
        // Draw custom background image
        ctx.drawImage(bgEffectState.bgImage, 0, 0, width, height);
    }

    ctx.restore();

    // Swap to canvas stream only after first successful frame render
    if (!bgEffectState.streamSwapped && bgEffectState.currentEffect !== 'none') {
        bgEffectState.streamSwapped = true;
        swapToCanvasStream();
    }
}

function swapToCanvasStream() {
    if (!bgEffectState.canvas || !bgEffectState.originalStream) return;

    const canvasStream = bgEffectState.canvas.captureStream(30);
    const processedVideoTrack = canvasStream.getVideoTracks()[0];

    const originalAudioTracks = bgEffectState.originalStream.getAudioTracks();
    const newStream = new MediaStream();
    newStream.addTrack(processedVideoTrack);
    originalAudioTracks.forEach(t => newStream.addTrack(t));

    bgEffectState.processedStream = newStream;
    VideoDetails.myVideoStream = newStream;

    if (VideoDetails.myVideo) {
        VideoDetails.myVideo.srcObject = newStream;
    }

    replaceVideoTrackInPeers(processedVideoTrack);
    console.log('Background effect stream swapped successfully');
}

async function enableBgEffect(effect) {
    bgEffectState.currentEffect = effect;

    // Save to localStorage
    localStorage.setItem('bgEffect', effect);

    showNotification('Loading background effect...');

    const segmenter = await initSegmenter();
    if (!segmenter) return;

    if (!VideoDetails.myVideoStream) return;

    // Store original stream if not already stored
    if (!bgEffectState.originalStream) {
        bgEffectState.originalStream = VideoDetails.myVideoStream;
    }

    // Create offscreen canvas if not exists
    if (!bgEffectState.canvas) {
        bgEffectState.canvas = document.createElement('canvas');
        bgEffectState.canvas.width = 640;
        bgEffectState.canvas.height = 480;
        bgEffectState.ctx = bgEffectState.canvas.getContext('2d');
    }

    // Reset swap flag so stream gets swapped on next successful frame
    bgEffectState.streamSwapped = false;

    // Start processing loop if not already running
    if (!bgEffectState.isProcessing) {
        bgEffectState.isProcessing = true;
        processBgFrame();
    }

    // Update button state
    if (bgEffectBtn) bgEffectBtn.classList.add('active');
}

async function processBgFrame(timestamp) {
    if (!bgEffectState.isProcessing || bgEffectState.currentEffect === 'none') return;

    // Throttle to ~30fps
    if (!bgEffectState._lastFrameTime) bgEffectState._lastFrameTime = 0;
    if (timestamp && timestamp - bgEffectState._lastFrameTime < 33) {
        bgEffectState.animFrameId = requestAnimationFrame(processBgFrame);
        return;
    }
    bgEffectState._lastFrameTime = timestamp;

    if (bgEffectState.originalStream && bgEffectState.segmenter) {
        const videoTrack = bgEffectState.originalStream.getVideoTracks()[0];
        if (videoTrack && videoTrack.readyState === 'live') {
            // Get video frame from a hidden video element
            let srcVideo = document.getElementById('bg-src-video');
            if (!srcVideo) {
                srcVideo = document.createElement('video');
                srcVideo.id = 'bg-src-video';
                srcVideo.style.display = 'none';
                srcVideo.playsInline = true;
                srcVideo.srcObject = bgEffectState.originalStream;
                srcVideo.muted = true;
                document.body.appendChild(srcVideo);
                try { await srcVideo.play(); } catch (e) {
                    console.error('Hidden video play failed:', e);
                }
            }

            if (srcVideo.readyState >= 2) {
                try {
                    await bgEffectState.segmenter.send({ image: srcVideo });
                } catch (err) {
                    console.error('Segmenter send failed:', err);
                    disableBgEffect();
                    showNotification('Background effect failed. Please try again.');
                    return;
                }
            }
        }
    }

    bgEffectState.animFrameId = requestAnimationFrame(processBgFrame);
}

function disableBgEffect() {
    bgEffectState.currentEffect = 'none';
    bgEffectState.isProcessing = false;
    bgEffectState.streamSwapped = false;
    localStorage.removeItem('bgEffect');

    if (bgEffectState.animFrameId) {
        cancelAnimationFrame(bgEffectState.animFrameId);
        bgEffectState.animFrameId = null;
    }

    // Remove hidden video element
    const srcVideo = document.getElementById('bg-src-video');
    if (srcVideo) srcVideo.remove();

    // Restore original stream
    if (bgEffectState.originalStream) {
        VideoDetails.myVideoStream = bgEffectState.originalStream;

        if (VideoDetails.myVideo) {
            VideoDetails.myVideo.srcObject = bgEffectState.originalStream;
        }

        // Replace track in peers with original
        const originalVideoTrack = bgEffectState.originalStream.getVideoTracks()[0];
        if (originalVideoTrack) {
            replaceVideoTrackInPeers(originalVideoTrack);
        }
    }

    bgEffectState.originalStream = null;
    bgEffectState.processedStream = null;

    // Update button state
    if (bgEffectBtn) bgEffectBtn.classList.remove('active');
}

function replaceVideoTrackInPeers(newTrack) {
    // Replace track in all PeerJS connections
    if (myPeer && myPeer.connections) {
        Object.values(myPeer.connections).forEach(conns => {
            conns.forEach(conn => {
                if (conn.peerConnection) {
                    const senders = conn.peerConnection.getSenders();
                    const videoSender = senders.find(s => s.track && s.track.kind === 'video');
                    if (videoSender) {
                        videoSender.replaceTrack(newTrack).catch(err => {
                            console.error('Error replacing video track:', err);
                        });
                    }
                }
            });
        });
    }
}

// Restore saved background effect on load
document.addEventListener('DOMContentLoaded', function() {
    const savedEffect = localStorage.getItem('bgEffect');
    if (savedEffect && savedEffect !== 'none') {
        // Wait for video stream to be ready
        const waitForStream = setInterval(function() {
            if (VideoDetails.myVideoStream) {
                clearInterval(waitForStream);
                // Update UI
                document.querySelectorAll('.bg-effect-option').forEach(o => {
                    o.classList.toggle('active', o.dataset.effect === savedEffect);
                });
                if (savedEffect === 'image') {
                    const presetsEl = document.getElementById('bgPresets');
                    if (presetsEl) presetsEl.style.display = 'block';
                }
                // For blur, enable immediately. For image, need a stored bg.
                if (savedEffect === 'blur') {
                    enableBgEffect('blur');
                }
            }
        }, 500);
    }
});
