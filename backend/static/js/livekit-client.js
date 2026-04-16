/**
 * LiveKit Meeting Client
 * Handles video call functionality using LiveKit SDK
 */

class LiveKitMeetingClient {
    constructor(roomId, username, isModerator = false) {
        this.roomId = roomId;
        this.username = username;
        this.isModerator = isModerator;
        this.room = null;
        this.localTracks = [];
        this.localScreenTrack = null;
        this.participants = new Map();
        this.isRecording = false;
        this.currentEgressId = null;
        
        // Callbacks
        this.onParticipantJoined = null;
        this.onParticipantLeft = null;
        this.onTrackSubscribed = null;
        this.onTrackUnsubscribed = null;
        this.onConnectionStateChanged = null;
        this.onRecordingStateChanged = null;
        this.onChatMessage = null;
    }
    
    /**
     * Initialize and connect to LiveKit room
     */
    async connect() {
        try {
            console.log('Connecting to LiveKit room:', this.roomId);
            
            // Get token from backend
            const tokenResponse = await fetch('/meeting/api/livekit/token/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCookie('csrftoken')
                },
                body: JSON.stringify({
                    room_id: this.roomId,
                    is_moderator: this.isModerator
                })
            });
            
            if (!tokenResponse.ok) {
                throw new Error('Failed to get LiveKit token');
            }
            
            const tokenData = await tokenResponse.json();
            console.log('Got LiveKit token');
            
            // Create room instance with optimal settings
            this.room = new LivekitClient.Room({
                // Adaptive streaming for low bandwidth
                adaptiveStream: true,
                
                // Simulcast for multiple quality levels
                dynacast: true,
                
                // Auto-reconnect on network loss
                reconnectionAttempts: 50,
                reconnectionDelay: 1000,
                
                // Audio settings for low latency
                audioCaptureDefaults: {
                    autoGainControl: true,
                    echoCancellation: true,
                    noiseSuppression: true
                },
                
                // Video settings
                videoCaptureDefaults: {
                    resolution: LivekitClient.VideoPresets.h720.resolution
                }
            });
            
            // Setup event listeners
            this.setupEventListeners();
            
            // Connect to room
            await this.room.connect(tokenData.url, tokenData.token);
            console.log('Connected to LiveKit room');
            
            // Publish local tracks (don't crash if no devices found)
            try {
                await this.publishLocalTracks();
            } catch (trackError) {
                console.warn('Could not publish local tracks:', trackError.message);
                console.warn('Joining meeting without camera/mic');
            }

            return true;

        } catch (error) {
            console.error('LiveKit connection error:', error);
            throw error;
        }
    }
    
    /**
     * Setup event listeners for room events
     */
    setupEventListeners() {
        // Participant joined
        this.room.on(LivekitClient.RoomEvent.ParticipantConnected, (participant) => {
            console.log('Participant joined:', participant.identity);
            this.participants.set(participant.identity, participant);
            
            if (this.onParticipantJoined) {
                this.onParticipantJoined(participant);
            }
        });
        
        // Participant left
        this.room.on(LivekitClient.RoomEvent.ParticipantDisconnected, (participant) => {
            console.log('Participant left:', participant.identity);
            this.participants.delete(participant.identity);
            
            if (this.onParticipantLeft) {
                this.onParticipantLeft(participant);
            }
        });
        
        // Track subscribed (receive remote video/audio)
        this.room.on(LivekitClient.RoomEvent.TrackSubscribed, (track, publication, participant) => {
            console.log('Track subscribed:', track.kind, 'from', participant.identity);
            
            if (this.onTrackSubscribed) {
                this.onTrackSubscribed(track, publication, participant);
            }
        });
        
        // Track unsubscribed
        this.room.on(LivekitClient.RoomEvent.TrackUnsubscribed, (track, publication, participant) => {
            console.log('Track unsubscribed:', track.kind);
            if (this.onTrackUnsubscribed) {
                this.onTrackUnsubscribed(track, publication, participant);
            }
        });
        
        // Connection state changes
        this.room.on(LivekitClient.RoomEvent.ConnectionStateChanged, (state) => {
            console.log('Connection state:', state);
            
            if (this.onConnectionStateChanged) {
                this.onConnectionStateChanged(state);
            }
        });
        
        // Reconnecting
        this.room.on(LivekitClient.RoomEvent.Reconnecting, () => {
            console.log('Connection lost, reconnecting...');
            this.showNotification('Connection lost, reconnecting...', 0);
        });
        
        // Reconnected
        this.room.on(LivekitClient.RoomEvent.Reconnected, () => {
            console.log('Reconnected successfully');
            this.showNotification('Reconnected!', 3000);
        });
        
        // Disconnected
        this.room.on(LivekitClient.RoomEvent.Disconnected, (reason) => {
            console.log('Disconnected:', reason);
        });
        
        // Data received (for chat, etc.)
        this.room.on(LivekitClient.RoomEvent.DataReceived, (payload, participant) => {
            const decoder = new TextDecoder();
            const raw = decoder.decode(payload);
            console.log('Data received from', participant?.identity, ':', raw);

            try {
                const data = JSON.parse(raw);
                if (data.type === 'chat' && this.onChatMessage) {
                    this.onChatMessage(data.username || participant?.name || 'Unknown', data.message);
                }
            } catch (e) {
                console.warn('Failed to parse data message:', e);
            }
        });
    }
    
    /**
     * Publish local video and audio tracks
     */
    async publishLocalTracks(options = {}) {
        const {
            video = true,
            audio = true,
            videoResolution = 'h720'
        } = options;

        // Try video + audio first, fall back gracefully
        let tracks = [];

        // Try both together
        try {
            tracks = await LivekitClient.createLocalTracks({
                audio: audio,
                video: video ? {
                    resolution: LivekitClient.VideoPresets[videoResolution].resolution,
                    frameRate: 30
                } : false
            });
        } catch (err) {
            console.warn('Could not get both audio+video, trying separately:', err.message);

            // Try audio only with explicit constraints
            try {
                const audioTracks = await LivekitClient.createLocalTracks({
                    audio: {
                        autoGainControl: true,
                        echoCancellation: true,
                        noiseSuppression: true,
                        sampleRate: 48000
                    },
                    video: false
                });
                tracks.push(...audioTracks);
            } catch (e) {
                console.warn('No microphone available:', e.message);
                // Last resort: try navigator.mediaDevices directly
                try {
                    const rawStream = await navigator.mediaDevices.getUserMedia({ audio: true });
                    const rawTrack = rawStream.getAudioTracks()[0];
                    if (rawTrack) {
                        const lkTrack = new LivekitClient.LocalAudioTrack(rawTrack);
                        tracks.push(lkTrack);
                        console.log('Got audio via raw getUserMedia fallback');
                    }
                } catch (e2) {
                    console.warn('Raw getUserMedia also failed:', e2.message);
                }
            }

            // Try video only
            try {
                const videoTracks = await LivekitClient.createLocalTracks({
                    audio: false,
                    video: { resolution: LivekitClient.VideoPresets[videoResolution].resolution, frameRate: 30 }
                });
                tracks.push(...videoTracks);
            } catch (e) {
                console.warn('No camera available:', e.message);
            }
        }

        if (tracks.length === 0) {
            console.warn('No media devices found — joining without camera/mic');
            return this.localTracks;
        }

        this.localTracks = tracks;

        // Publish tracks to room — audio first for reliability
        const sorted = [...tracks].sort((a) => (a.kind === 'audio' ? -1 : 1));
        for (const track of sorted) {
            try {
                const opts = {};
                if (track.kind === 'video') {
                    opts.simulcast = true;
                    opts.videoEncoding = { maxBitrate: 1500000, maxFramerate: 30 };
                }
                await this.room.localParticipant.publishTrack(track, opts);
                console.log('Published', track.kind, 'track successfully');
            } catch (err) {
                console.error('Failed to publish', track.kind, 'track:', err);
            }
        }

        return this.localTracks;
    }
    
    /**
     * Toggle local video on/off
     */
    async toggleVideo() {
        const videoTrack = this.localTracks.find(t => t.kind === 'video');
        
        if (videoTrack) {
            if (videoTrack.isMuted) {
                await videoTrack.unmute();
                return true; // Video on
            } else {
                await videoTrack.mute();
                return false; // Video off
            }
        }
        
        return false;
    }
    
    /**
     * Toggle local audio on/off
     */
    async toggleAudio() {
        const audioTrack = this.localTracks.find(t => t.kind === 'audio');
        
        if (audioTrack) {
            if (audioTrack.isMuted) {
                await audioTrack.unmute();
                return true; // Audio on
            } else {
                await audioTrack.mute();
                return false; // Audio off
            }
        }
        
        return false;
    }
    
    /**
     * Start screen sharing
     */
    async startScreenShare() {
        try {
            let screenTracks;
            // Try with system audio first, fall back without
            try {
                screenTracks = await LivekitClient.createLocalScreenTracks({
                    audio: true
                });
            } catch (audioErr) {
                console.warn('Screen share with audio failed, trying without:', audioErr.message);
                screenTracks = await LivekitClient.createLocalScreenTracks({
                    audio: false
                });
            }

            // Publish all screen tracks (video + optional audio)
            for (const track of screenTracks) {
                await this.room.localParticipant.publishTrack(track);
            }

            // Store the video screen track for local display
            this.localScreenTrack = screenTracks.find(t => t.kind === 'video') || screenTracks[0];
            console.log('Screen sharing started');

            // Listen for browser "Stop sharing" button
            if (this.localScreenTrack.mediaStreamTrack) {
                this.localScreenTrack.mediaStreamTrack.onended = () => {
                    console.log('Screen share ended by browser');
                    this.stopScreenShare();
                    // Dispatch event so UI can update
                    window.dispatchEvent(new CustomEvent('screenshare-ended'));
                };
            }

            return this.localScreenTrack;

        } catch (error) {
            console.error('Screen share error:', error);
            throw error;
        }
    }
    
    /**
     * Stop screen sharing
     */
    async stopScreenShare() {
        // trackPublications is a Map in LiveKit v2 — iterate properly
        const publications = this.room.localParticipant.trackPublications;
        for (const [, pub] of publications) {
            if (pub.source === LivekitClient.Track.Source.ScreenShare ||
                pub.source === LivekitClient.Track.Source.ScreenShareAudio) {
                try {
                    await this.room.localParticipant.unpublishTrack(pub.track);
                    pub.track.stop();
                } catch (e) {
                    console.warn('Error unpublishing screen track:', e);
                }
            }
        }
        this.localScreenTrack = null;
        console.log('Screen sharing stopped');
    }
    
    /**
     * Start recording the meeting
     */
    async startRecording() {
        try {
            const response = await fetch(`/meeting/api/livekit/room/${this.roomId}/start-recording/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCookie('csrftoken')
                },
                body: JSON.stringify({})
            });
            
            if (!response.ok) {
                throw new Error('Failed to start recording');
            }
            
            const data = await response.json();
            this.isRecording = true;
            this.currentEgressId = data.egress_id;
            
            console.log('Recording started:', data.egress_id);
            
            if (this.onRecordingStateChanged) {
                this.onRecordingStateChanged(true);
            }
            
            return data;
            
        } catch (error) {
            console.error('Failed to start recording:', error);
            throw error;
        }
    }
    
    /**
     * Stop recording the meeting
     */
    async stopRecording() {
        try {
            const response = await fetch(`/meeting/api/livekit/room/${this.roomId}/stop-recording/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCookie('csrftoken')
                },
                body: JSON.stringify({
                    egress_id: this.currentEgressId
                })
            });
            
            if (!response.ok) {
                throw new Error('Failed to stop recording');
            }
            
            const data = await response.json();
            this.isRecording = false;
            this.currentEgressId = null;
            
            console.log('Recording stopped');
            
            if (this.onRecordingStateChanged) {
                this.onRecordingStateChanged(false);
            }
            
            return data;
            
        } catch (error) {
            console.error('Failed to stop recording:', error);
            throw error;
        }
    }
    
    /**
     * Send chat message to room
     */
    async sendChatMessage(message) {
        const encoder = new TextEncoder();
        const data = encoder.encode(JSON.stringify({
            type: 'chat',
            message: message,
            username: this.username,
            timestamp: Date.now()
        }));
        
        try {
            await this.room.localParticipant.publishData(data, { reliable: true });
        } catch (e) {
            // Fallback for older API
            try {
                await this.room.localParticipant.publishData(data, LivekitClient.DataPacket_Kind.RELIABLE);
            } catch (e2) {
                console.error('Failed to send chat message:', e2);
            }
        }
    }
    
    /**
     * Get list of participants
     */
    getParticipants() {
        if (!this.room) return [];
        const participants = this.room.remoteParticipants || this.room.participants;
        if (!participants) return [];
        return Array.from(participants.values());
    }

    /**
     * Remove a participant from the room (moderator only)
     */
    async removeParticipant(participantIdentity) {
        try {
            const response = await fetch(`/meeting/api/livekit/room/${this.roomId}/remove-participant/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCookie('csrftoken')
                },
                body: JSON.stringify({ identity: participantIdentity })
            });
            if (!response.ok) throw new Error('Failed to remove participant');
            return await response.json();
        } catch (error) {
            console.error('Failed to remove participant:', error);
            throw error;
        }
    }
    
    /**
     * Disconnect from room
     */
    async disconnect() {
        if (this.room) {
            // Stop recording if active
            if (this.isRecording) {
                await this.stopRecording();
            }
            
            // Stop all local tracks
            this.localTracks.forEach(track => track.stop());
            
            // Disconnect
            await this.room.disconnect();
            console.log('Disconnected from room');
        }
    }
    
    /**
     * Get CSRF token from cookies
     */
    getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
    
    /**
     * Show notification to user
     */
    showNotification(message, duration = 5000) {
        const existing = document.querySelector('.room-notification');
        if (existing) existing.remove();
        
        const el = document.createElement('div');
        el.className = 'room-notification';
        el.style.cssText = 'position:fixed;top:20px;left:50%;transform:translateX(-50%);z-index:10000;background:#1e1e2e;color:#fff;padding:12px 24px;border-radius:8px;font-size:14px;box-shadow:0 4px 12px rgba(0,0,0,0.3);transition:opacity 0.3s;';
        el.textContent = message;
        document.body.appendChild(el);
        
        if (duration > 0) {
            setTimeout(() => {
                el.style.opacity = '0';
                setTimeout(() => el.remove(), 300);
            }, duration);
        }
    }
}

// Export for use in other scripts
window.LiveKitMeetingClient = LiveKitMeetingClient;