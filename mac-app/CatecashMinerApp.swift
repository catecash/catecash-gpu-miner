import AppKit
import SwiftUI

@MainActor
final class MinerRunner: ObservableObject {
    @Published var log = "Ready. Select your Catecash RPC and payout address."
    @Published var isRunning = false
    @Published var isBusy = false
    @Published var status = "Idle"

    private var process: Process?
    private var outputPipe: Pipe?
    private var miningArguments: [String]?
    private var miningScript = "solo.py"
    private var pendingRestartArguments: [String]?
    private var stopRequested = false
    private var activityLines: [String] = []
    private var pendingLine = ""

    func launch(script: String, arguments: [String], mining: Bool) {
        guard !isBusy else { return }
        guard let resources = Bundle.main.resourceURL else {
            append("App resources are missing.")
            return
        }
        let process = Process()
        let pipe = Pipe()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        process.arguments = [resources.appendingPathComponent(script).path] + arguments
        process.currentDirectoryURL = resources
        process.standardOutput = pipe
        process.standardError = pipe
        process.environment = [
            "PATH": "/usr/bin:/bin",
            "HOME": NSHomeDirectory(),
            "LANG": "en_US.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1"
        ]
        self.process = process
        self.outputPipe = pipe
        if mining {
            miningArguments = arguments
            miningScript = script
            stopRequested = false
        }
        log = ""
        activityLines = []
        pendingLine = ""
        isBusy = true
        isRunning = mining
        status = mining ? "Starting GPU miner…" : "Checking RPC…"

        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty, let message = String(data: data, encoding: .utf8) else { return }
            Task { @MainActor [weak self] in self?.append(message) }
        }
        process.terminationHandler = { [weak self] finished in
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.outputPipe?.fileHandleForReading.readabilityHandler = nil
                self.process = nil
                self.outputPipe = nil
                self.isBusy = false
                self.isRunning = false
                if let arguments = self.pendingRestartArguments, !self.stopRequested {
                    self.pendingRestartArguments = nil
                    self.launch(script: self.miningScript, arguments: arguments, mining: true)
                } else {
                    self.miningArguments = nil
                    self.pendingRestartArguments = nil
                    self.status = finished.terminationStatus == 0 ? "Finished" : "Stopped (exit \(finished.terminationStatus))"
                }
            }
        }
        do {
            try process.run()
        } catch {
            pipe.fileHandleForReading.readabilityHandler = nil
            self.process = nil
            self.outputPipe = nil
            isBusy = false
            isRunning = false
            miningArguments = nil
            pendingRestartArguments = nil
            status = "Could not start"
            append(error.localizedDescription)
        }
    }

    func stop() {
        stopRequested = true
        pendingRestartArguments = nil
        guard let process, process.isRunning else { return }
        status = "Stopping…"
        process.interrupt()
    }

    func restartMining(script: String, arguments: [String]) {
        guard isRunning, !stopRequested, script == miningScript, arguments != miningArguments else { return }
        pendingRestartArguments = arguments
        guard let process, process.isRunning else { return }
        status = "Applying GPU duty cycle…"
        process.interrupt()
    }

    private func append(_ message: String) {
        pendingLine += message
        let parts = pendingLine.components(separatedBy: "\n")
        pendingLine = parts.last ?? ""
        activityLines.insert(contentsOf: parts.dropLast().reversed(), at: 0)
        if activityLines.count > 600 { activityLines.removeLast(activityLines.count - 600) }
        let visibleLines = pendingLine.isEmpty ? activityLines : [pendingLine] + activityLines
        log = String(visibleLines.joined(separator: "\n").prefix(30_000))
        if message.contains("Accepted block at height") { status = "Block accepted" }
        else if message.contains("Accepted share ") { status = "Share accepted" }
        else if message.contains("Working on height") { status = "Mining" }
    }
}

struct ContentView: View {
    @StateObject private var runner = MinerRunner()
    @AppStorage("rpcURL") private var rpcURL = "http://127.0.0.1:34342"
    @AppStorage("cookiePath") private var cookiePath = ""
    @AppStorage("network") private var network = "catecash-devnet"
    @AppStorage("payoutAddress") private var payoutAddress = ""
    @AppStorage("gpuDutyCycle") private var intensity = 50.0
    @AppStorage("keepLatestInView") private var keepLatestInView = true
    @AppStorage("miningMode") private var miningMode = "solo"
    @AppStorage("poolURL") private var poolURL = ""
    @AppStorage("workerName") private var workerName = "mac"

    private var commonArguments: [String] {
        var arguments = ["--rpc-url", rpcURL.trimmingCharacters(in: .whitespacesAndNewlines),
                         "--network", network]
        let payout = payoutAddress.trimmingCharacters(in: .whitespacesAndNewlines)
        if !payout.isEmpty { arguments += ["--payout-address", payout] }
        if !cookiePath.isEmpty { arguments += ["--cookie-file", cookiePath] }
        return arguments
    }

    private var canStart: Bool {
        !runner.isBusy && (miningMode == "pool"
            ? !poolURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !payoutAddress.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            : !rpcURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
    }

    private var poolArguments: [String] {
        ["--pool-url", poolURL.trimmingCharacters(in: .whitespacesAndNewlines),
         "--network", network,
         "--payout-address", payoutAddress.trimmingCharacters(in: .whitespacesAndNewlines),
         "--worker", workerName.trimmingCharacters(in: .whitespacesAndNewlines)]
    }

    private var miningArguments: [String] {
        (miningMode == "pool" ? poolArguments : commonArguments) + ["--intensity", String(Int(intensity))]
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Catecash Miner").font(.largeTitle.bold())
                    Text("Mine solo or connect to a pool with your Mac GPU").foregroundStyle(.secondary)
                }
                Spacer()
                Label(runner.status, systemImage: runner.isRunning ? "bolt.fill" : "circle.fill")
                    .foregroundStyle(runner.isRunning ? .green : .secondary)
            }

            Form {
                Picker("Mode", selection: $miningMode) {
                    Text("Solo").tag("solo")
                    Text("Pool").tag("pool")
                }
                Picker("Network", selection: $network) {
                    Text("Devnet").tag("catecash-devnet")
                    Text("Testnet").tag("catecash-testnet")
                    Text("Mainnet").tag("catecash-mainnet")
                }
                if miningMode == "pool" {
                    TextField("Pool URL", text: $poolURL)
                    TextField("Your payout address", text: $payoutAddress)
                    TextField("Worker name", text: $workerName)
                } else {
                    TextField("RPC URL", text: $rpcURL)
                    HStack {
                        TextField("RPC cookie file", text: $cookiePath)
                        Button("Choose…") { chooseCookie() }
                    }
                    TextField("Payout override (optional)", text: $payoutAddress)
                }
            }
            .formStyle(.grouped)
            .disabled(runner.isBusy)

            HStack(spacing: 12) {
                Text("GPU duty cycle")
                Slider(value: $intensity, in: 10...100, step: 10)
                    .accessibilityLabel("GPU duty cycle")
                Text("\(Int(intensity))%")
                    .monospacedDigit()
                    .frame(width: 48, alignment: .trailing)
            }
            .padding(12)
            .background(Color(nsColor: .controlBackgroundColor))
            .clipShape(RoundedRectangle(cornerRadius: 8))

            Text(miningMode == "pool"
                 ? "Pool mode is a prototype. Use a trusted pool that verifies shares and publishes payout rules. Your payout address is required. The GPU duty cycle limits average activity; bursts may use the full GPU."
                 : "Leave payout override blank to use the node's configured mining address. The GPU duty cycle defaults to 50% and limits average active time. Changes apply five seconds after you stop moving the slider. Each mining burst may still reach full GPU usage.")
                .font(.caption)
                .foregroundStyle(.secondary)

            HStack {
                Button(miningMode == "pool" ? "Test Pool" : "Test RPC") {
                    runner.launch(script: miningMode == "pool" ? "pool_client.py" : "preflight.py",
                                  arguments: miningMode == "pool" ? poolArguments + ["--check"] : commonArguments,
                                  mining: false)
                }
                    .disabled(!canStart)
                Spacer()
                Button("Stop") { runner.stop() }
                    .disabled(!runner.isRunning)
                Button("Start Mining") {
                    runner.launch(script: miningMode == "pool" ? "pool_client.py" : "solo.py",
                                  arguments: miningArguments, mining: true)
                }
                .buttonStyle(.borderedProminent)
                .disabled(!canStart)
            }

            HStack {
                Text("Activity").font(.headline)
                Spacer()
                Button {
                    keepLatestInView.toggle()
                } label: {
                    Label("Keep latest in view", systemImage: keepLatestInView ? "pin.fill" : "pin")
                }
                .accessibilityValue(keepLatestInView ? "On" : "Off")
            }
            ScrollViewReader { scrollProxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 0) {
                        Color.clear.frame(height: 0).id("latestActivity")
                        Text(runner.log.isEmpty ? "Waiting for output…" : runner.log)
                            .font(.system(.caption, design: .monospaced))
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .textSelection(.enabled)
                    }
                    .padding(10)
                }
                .onChange(of: runner.log) { _ in
                    if keepLatestInView { scrollProxy.scrollTo("latestActivity", anchor: .top) }
                }
                .onChange(of: keepLatestInView) { enabled in
                    if enabled { scrollProxy.scrollTo("latestActivity", anchor: .top) }
                }
            }
            .frame(minHeight: 180)
            .background(Color(nsColor: .textBackgroundColor))
            .clipShape(RoundedRectangle(cornerRadius: 8))
        }
        .padding(24)
        .frame(minWidth: 670, minHeight: 680)
        .onDisappear { runner.stop() }
        .task(id: intensity) {
            try? await Task.sleep(nanoseconds: 5_000_000_000)
            guard !Task.isCancelled else { return }
            runner.restartMining(script: miningMode == "pool" ? "pool_client.py" : "solo.py",
                                 arguments: miningArguments)
        }
    }

    private func chooseCookie() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = false
        panel.canChooseFiles = true
        panel.showsHiddenFiles = true
        if panel.runModal() == .OK, let url = panel.url { cookiePath = url.path }
    }
}

@main
struct CatecashMinerApp: App {
    var body: some Scene {
        WindowGroup { ContentView() }
    }
}
