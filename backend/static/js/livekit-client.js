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
        this.participants = new Map();
        this.isRecording = false;
        this.currentEgressId = null;
        
        // Callbacks
        this.onParticipantJoined = null;
        this.onParticipantLeft = null;
        this.onTrackSubscribed = null;
        this.onConnectionStateChanged = null;
        this.onRecordingStateChanged = null;
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
            
            // Publish local tracks
            await this.publishLocalTracks();
            
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
            const message = decoder.decode(payload);
            console.log('Data received from', participant?.identity, ':', message);
        });
    }
    
    /**
     * Publish local video and audio tracks
     */
    async publishLocalTracks(options = {}) {
        try {
            const {
                video = true,
                audio = true,
                videoResolution = 'h720'
            } = options;
            
            // Create local tracks
            const tracks = await LivekitClient.createLocalTracks({
                audio: audio,
                video: video ? {
                    resolution: LivekitClient.VideoPresets[videoResolution].resolution,
                    frameRate: 30
                } : false
            });
            
            this.localTracks = tracks;
            
            // Publish tracks to room
            for (const track of tracks) {
                await this.room.localParticipant.publishTrack(track, {
                    // Enable simulcast for adaptive quality
                    simulcast: track.kind === 'video',
                    
                    // Video encoding settings
                    videoEncoding: track.kind === 'video' ? {
                        maxBitrate: 1500000, // 1.5 Mbps max
                        maxFramerate: 30
                    } : undefined
                });
                
                console.log('Published', track.kind, 'track');
            }
            
            return this.localTracks;
            
        } catch (error) {
            console.error('Failed to publish tracks:', error);
            throw error;
        }
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
            const screenTrack = await LivekitClient.createLocalScreenTracks({
                audio: true // Include system audio
            });
            
            await this.room.localParticipant.publishTrack(screenTrack[0]);
            console.log('Screen sharing started');
            
            return screenTrack[0];
            
        } catch (error) {
            console.error('Screen share error:', error);
            throw error;
        }
    }
    
    /**
     * Stop screen sharing
     */
    async stopScreenShare() {
        const screenTrack = this.room.localParticipant.videoTrackPublications
            .find(pub => pub.source === LivekitClient.Track.Source.ScreenShare);
        
        if (screenTrack) {
            await this.room.localParticipant.unpublishTrack(screenTrack.track);
            screenTrack.track.stop();
            console.log('Screen sharing stopped');
        }
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
        
        await this.room.localParticipant.publishData(data, LivekitClient.DataPacket_Kind.RELIABLE);
    }
    
    /**
     * Get list of participants
     */
    getParticipants() {
        return Array.from(this.room.participants.values());
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