#import "LegacyStore.h"

@implementation LegacyStore

- (void)store:(NSString *)value
    completion:(void (^)(BOOL ok))completion
{
    void (^write)(void) = ^{
        NSLog(@"{ stored: %@ }", value);
    };
    write();
    completion(YES);
}

+ (instancetype)sharedStore {
    static LegacyStore *store;
    return store;
}

@end
