#import <Foundation/Foundation.h>

@class Account;

@interface OrderStore : NSObject

- (void)save:(Account *)account;

@end
