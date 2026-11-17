#import <Signal/Account.h>
#import "OrderStore.h"

@implementation OrderStore

- (void)save:(Account *)account {
    NSLog(@"%@", account.identifier);
}

@end
