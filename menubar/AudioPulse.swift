import Foundation
import AVFoundation

/// 麦克风音量包络 → 灯光律动
///
/// 用 AVAudioEngine 抓输入，算短时 RMS，做指数平滑得到 0..1 的 level。
/// 需要「麦克风」权限（首次开启时会弹系统授权）。
final class AudioPulse {

    static let shared = AudioPulse()

    private let engine = AVAudioEngine()
    private let lock = NSLock()
    private var _level: Double = 0
    private(set) var isRunning = false

    private init() {}

    /// 当前音量包络，0..1
    var level: Double {
        lock.lock()
        defer { lock.unlock() }
        return _level
    }

    /// 请求麦克风权限（异步回调在主线程）
    static func requestPermission(_ completion: @escaping (Bool) -> Void) {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:
            completion(true)
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .audio) { granted in
                DispatchQueue.main.async { completion(granted) }
            }
        default:
            completion(false)
        }
    }

    @discardableResult
    func start() -> Bool {
        guard !isRunning else { return true }
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0 else { return false }

        input.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak self] buffer, _ in
            guard let self, let ch = buffer.floatChannelData?[0] else { return }
            let n = Int(buffer.frameLength)
            guard n > 0 else { return }
            var sum = 0.0
            for i in 0..<n {
                let v = Double(ch[i])
                sum += v * v
            }
            let rms = (sum / Double(n)).squareRoot()
            // 放大 + 对数压缩，让小声也有反应
            let norm = min(1.0, (rms * 12.0).squareRoot())
            self.lock.lock()
            self._level = self._level * 0.65 + norm * 0.35
            self.lock.unlock()
        }

        do {
            engine.prepare()
            try engine.start()
            isRunning = true
            return true
        } catch {
            NSLog("AudioPulse start failed: \(error)")
            return false
        }
    }

    func stop() {
        guard isRunning else { return }
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        isRunning = false
        lock.lock()
        _level = 0
        lock.unlock()
    }
}
