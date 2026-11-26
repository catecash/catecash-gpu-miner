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
        log = ""
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
                self?.outputPipe?.fileHandleForReading.readabilityHandler = nil
                self?.process = nil
                self?.outputPipe = nil
                self?.isBusy = false
                self?.isRunning = false
                self?.status = finished.terminationStatus == 0 ? "Finished" : "Stopped (exit \(finished.terminationStatus))"
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
            status = "Could not start"
            append(error.localizedDescription)
        }
    }

    func stop() {
        guard let process, process.isRunning else { return }
        status = "Stopping…"
        process.interrupt()
    }

    private func append(_ message: String) {
        log += message
        if log.count > 30_000 { log = String(log.suffix(30_000)) }
        if message.contains("Accepted block at height") { status = "Block accepted" }
        else if message.contains("Working on height") { status = "Mining" }
    }
}

struct ContentView: View {
    @StateObject private var runner = MinerRunner()
    @AppStorage("rpcURL") private var rpcURL = "http://127.0.0.1:34342"
    @AppStorage("cookiePath") private var cookiePath = ""
    @AppStorage("network") private var network = "catecash-devnet"
    @AppStorage("payoutAddress") private var payoutAddress = ""
    @AppStorage("intensity") private var intensity = 100.0

    private var commonArguments: [String] {
        var arguments = ["--rpc-url", rpcURL.trimmingCharacters(in: .whitespacesAndNewlines),
                         "--network", network]
        let payout = payoutAddress.trimmingCharacters(in: .whitespacesAndNewlines)
        if !payout.isEmpty { arguments += ["--payout-address", payout] }
        if !cookiePath.isEmpty { arguments += ["--cookie-file", cookiePath] }
        return arguments
    }

    private var canStart: Bool {
        !runner.isBusy && !rpcURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Catecash Miner").font(.largeTitle.bold())
                    Text("Mine with your Mac GPU").foregroundStyle(.secondary)
                }
                Spacer()
                Label(runner.status, systemImage: runner.isRunning ? "bolt.fill" : "circle.fill")
                    .foregroundStyle(runner.isRunning ? .green : .secondary)
            }

            Form {
                Picker("Network", selection: $network) {
                    Text("Devnet").tag("catecash-devnet")
                    Text("Testnet").tag("catecash-testnet")
                    Text("Mainnet").tag("catecash-mainnet")
                }
                TextField("RPC URL", text: $rpcURL)
                HStack {
                    TextField("RPC cookie file", text: $cookiePath)
                    Button("Choose…") { chooseCookie() }
                }
                TextField("Payout override (optional)", text: $payoutAddress)
                HStack {
                    Slider(value: $intensity, in: 10...100, step: 10)
                    Text("\(Int(intensity))%")
                        .monospacedDigit()
                        .frame(width: 48, alignment: .trailing)
                }
                .labelStyle(.titleAndIcon)
                .accessibilityLabel("GPU intensity")
            }
            .formStyle(.grouped)

            Text("Leave payout override blank to use the node's configured mining address. GPU intensity controls approximate active time; macOS does not offer a per-core limit.")
                .font(.caption)
                .foregroundStyle(.secondary)

            HStack {
                Button("Test RPC") { runner.launch(script: "preflight.py", arguments: commonArguments, mining: false) }
                    .disabled(!canStart)
                Spacer()
                Button("Stop") { runner.stop() }
                    .disabled(!runner.isRunning)
                Button("Start Mining") {
                    runner.launch(script: "solo.py", arguments: commonArguments + ["--intensity", String(Int(intensity))], mining: true)
                }
                .buttonStyle(.borderedProminent)
                .disabled(!canStart)
            }

            Text("Activity").font(.headline)
            ScrollView {
                Text(runner.log.isEmpty ? "Waiting for output…" : runner.log)
                    .font(.system(.caption, design: .monospaced))
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .textSelection(.enabled)
                    .padding(10)
            }
            .frame(minHeight: 180)
            .background(Color(nsColor: .textBackgroundColor))
            .clipShape(RoundedRectangle(cornerRadius: 8))
        }
        .padding(24)
        .frame(minWidth: 670, minHeight: 620)
        .onDisappear { runner.stop() }
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
