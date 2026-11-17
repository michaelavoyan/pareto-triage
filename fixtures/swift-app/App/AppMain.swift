import Foundation

final class AppMain {
    func makeCache() -> OrderCache {
        return OrderCache.shared
    }

    func makeStore() -> OrderStore {
        return OrderStore()
    }
}
