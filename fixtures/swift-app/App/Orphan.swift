import Foundation

// Not listed in any target's Sources phase: the project does not compile it.
struct OrphanType {
    let cache = OrderCache.shared
}
