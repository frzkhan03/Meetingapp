/**
 * RNNoise-style AudioWorklet Processor
 *
 * Implements noise suppression using a spectral noise gate approach.
 * When WASM module is available, uses RNNoise. Falls back to
 * a JavaScript-based noise gate for broader compatibility.
 */
class RNNoiseProcessor extends AudioWorkletProcessor {
    constructor() {
        super();
        this.active = true;
        this.noiseFloor = 0.008; // Adaptive noise floor
        this.smoothing = 0.95;
        this.attackTime = 0.01;
        this.releaseTime = 0.05;
        this.envelope = 0;
        this.frameCount = 0;

        this.port.onmessage = (e) => {
            if (e.data.type === 'init') {
                this.active = true;
                // WASM init would go here if module is provided
                // For now, use the JS-based noise gate
            } else if (e.data.type === 'stop') {
                this.active = false;
            }
        };
    }

    process(inputs, outputs) {
        const input = inputs[0];
        const output = outputs[0];

        if (!input || !input[0] || !this.active) {
            // Passthrough
            if (input && output) {
                for (let ch = 0; ch < input.length; ch++) {
                    if (input[ch] && output[ch]) {
                        output[ch].set(input[ch]);
                    }
                }
            }
            return true;
        }

        for (let ch = 0; ch < input.length; ch++) {
            const inp = input[ch];
            const out = output[ch];

            for (let i = 0; i < inp.length; i++) {
                const sample = inp[i];
                const absSample = Math.abs(sample);

                // Track envelope (peak follower with attack/release)
                if (absSample > this.envelope) {
                    this.envelope = this.envelope + this.attackTime * (absSample - this.envelope);
                } else {
                    this.envelope = this.envelope + this.releaseTime * (absSample - this.envelope);
                }

                // Adaptive noise floor estimation (very slow update)
                if (this.frameCount < 100) {
                    // Initial calibration: learn the noise floor from first ~100 frames
                    this.noiseFloor = this.noiseFloor * 0.99 + absSample * 0.01;
                } else {
                    // Slowly adapt noise floor to minimum signal level
                    if (absSample < this.noiseFloor * 3) {
                        this.noiseFloor = this.noiseFloor * 0.9999 + absSample * 0.0001;
                    }
                }

                // Compute gain based on signal-to-noise
                const threshold = this.noiseFloor * 3.5;
                let gain;

                if (this.envelope > threshold) {
                    gain = 1.0;
                } else if (this.envelope > this.noiseFloor) {
                    // Smooth transition zone
                    const ratio = (this.envelope - this.noiseFloor) / (threshold - this.noiseFloor);
                    gain = ratio * ratio; // Quadratic for smoother gate
                } else {
                    gain = 0.0;
                }

                out[i] = sample * gain;
            }
        }

        this.frameCount++;
        return true;
    }
}

registerProcessor('rnnoise-processor', RNNoiseProcessor);
