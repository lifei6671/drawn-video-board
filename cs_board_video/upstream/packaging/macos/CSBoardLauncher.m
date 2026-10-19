#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>

@interface CSBoardLauncher : NSObject <NSApplicationDelegate>
@property(nonatomic, strong) NSWindow *window;
@property(nonatomic, strong) WKWebView *webView;
@property(nonatomic, strong) NSTask *backendProcess;
@property(nonatomic, strong) NSTask *frontendProcess;
@property(nonatomic, strong) NSURL *resourceRoot;
@property(nonatomic, strong) NSURL *stateDirectory;
@property(nonatomic, strong) NSTimer *readinessTimer;
@property(nonatomic) NSInteger readinessAttempts;
@end

@implementation CSBoardLauncher

- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];
    [self createWindow];
    [self launchServices];
    [NSApp activateIgnoringOtherApps:YES];
    [self.window makeKeyAndOrderFront:nil];
}

- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)sender {
    return YES;
}

- (void)applicationWillTerminate:(NSNotification *)notification {
    [self.readinessTimer invalidate];
    [self terminateTask:self.frontendProcess];
    [self terminateTask:self.backendProcess];
}

- (void)createWindow {
    NSRect contentRect = NSMakeRect(0, 0, 1440, 920);
    self.window = [[NSWindow alloc] initWithContentRect:contentRect
                                               styleMask:(NSWindowStyleMaskTitled |
                                                          NSWindowStyleMaskClosable |
                                                          NSWindowStyleMaskMiniaturizable |
                                                          NSWindowStyleMaskResizable)
                                                 backing:NSBackingStoreBuffered
                                                   defer:NO];
    self.window.title = @"有温度出品｜白板声画工坊";
    self.window.minSize = NSMakeSize(960, 640);
    [self.window center];

    WKWebViewConfiguration *configuration = [[WKWebViewConfiguration alloc] init];
    self.webView = [[WKWebView alloc] initWithFrame:contentRect configuration:configuration];
    self.webView.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    self.window.contentView = self.webView;
    [self showStatus:@"正在启动白板声画工坊…"];
}

- (void)launchServices {
    NSURL *bundleRoot = NSBundle.mainBundle.resourceURL;
    if (!bundleRoot) {
        [self showStatus:@"无法定位应用资源"];
        return;
    }

    self.resourceRoot = [bundleRoot URLByAppendingPathComponent:@"app" isDirectory:YES];
    NSURL *runtimeRoot = [bundleRoot URLByAppendingPathComponent:@"runtime" isDirectory:YES];
    NSString *applicationSupport = NSSearchPathForDirectoriesInDomains(NSApplicationSupportDirectory, NSUserDomainMask, YES).firstObject;
    self.stateDirectory = [[NSURL fileURLWithPath:applicationSupport] URLByAppendingPathComponent:@"CS Board" isDirectory:YES];

    NSError *error = nil;
    if (![[NSFileManager defaultManager] createDirectoryAtURL:self.stateDirectory
                                   withIntermediateDirectories:YES
                                                    attributes:nil
                                                         error:&error]) {
        [self showStatus:[NSString stringWithFormat:@"无法创建数据目录：%@", error.localizedDescription]];
        return;
    }
    if (![self startBackendWithRuntimeRoot:runtimeRoot error:&error] ||
        ![self startFrontendWithRuntimeRoot:runtimeRoot error:&error]) {
        [self showStatus:[NSString stringWithFormat:@"启动失败：%@", error.localizedDescription]];
        return;
    }
    [self waitForServices];
}

- (BOOL)startBackendWithRuntimeRoot:(NSURL *)runtimeRoot error:(NSError **)error {
    NSURL *executable = [[runtimeRoot URLByAppendingPathComponent:@"backend" isDirectory:YES]
                         URLByAppendingPathComponent:@"CSBoardBackend"];
    if (![[NSFileManager defaultManager] isExecutableFileAtPath:executable.path]) {
        if (error) *error = [self missingResourceError:executable.path];
        return NO;
    }

    NSTask *process = [[NSTask alloc] init];
    process.executableURL = executable;
    process.currentDirectoryURL = self.resourceRoot;
    process.environment = [self environmentWithRuntimeRoot:runtimeRoot node:[runtimeRoot URLByAppendingPathComponent:@"node"]];
    process.standardOutput = [self logPipeNamed:@"backend-output.log"];
    process.standardError = [self logPipeNamed:@"backend-error.log"];
    [process launchAndReturnError:error];
    if (error && *error) return NO;
    self.backendProcess = process;
    return YES;
}

- (BOOL)startFrontendWithRuntimeRoot:(NSURL *)runtimeRoot error:(NSError **)error {
    NSURL *node = [runtimeRoot URLByAppendingPathComponent:@"node"];
    NSURL *webRoot = [self.resourceRoot URLByAppendingPathComponent:@"web" isDirectory:YES];
    NSURL *entry = [[[[webRoot URLByAppendingPathComponent:@"node_modules" isDirectory:YES]
                      URLByAppendingPathComponent:@"vinext" isDirectory:YES]
                     URLByAppendingPathComponent:@"dist" isDirectory:YES]
                    URLByAppendingPathComponent:@"cli.js"];
    if (![[NSFileManager defaultManager] isExecutableFileAtPath:node.path] ||
        ![[NSFileManager defaultManager] fileExistsAtPath:entry.path]) {
        if (error) *error = [self missingResourceError:entry.path];
        return NO;
    }

    NSTask *process = [[NSTask alloc] init];
    process.executableURL = node;
    process.arguments = @[entry.path, @"start", @"--host", @"127.0.0.1", @"--port", @"13000"];
    process.currentDirectoryURL = webRoot;
    process.environment = [self environmentWithRuntimeRoot:runtimeRoot node:node];
    process.standardOutput = [self logPipeNamed:@"frontend-output.log"];
    process.standardError = [self logPipeNamed:@"frontend-error.log"];
    [process launchAndReturnError:error];
    if (error && *error) return NO;
    self.frontendProcess = process;
    return YES;
}

- (NSDictionary<NSString *, NSString *> *)environmentWithRuntimeRoot:(NSURL *)runtimeRoot node:(NSURL *)node {
    NSMutableDictionary *environment = [NSProcessInfo.processInfo.environment mutableCopy];
    NSString *path = environment[@"PATH"] ?: @"/usr/bin:/bin:/usr/sbin:/sbin";
    environment[@"PATH"] = [NSString stringWithFormat:@"%@:%@", runtimeRoot.path, path];
    environment[@"CS_BOARD_ROOT"] = self.resourceRoot.path;
    environment[@"CS_BOARD_STATE_DIR"] = self.stateDirectory.path;
    environment[@"CS_BOARD_NODE"] = node.path;
    environment[@"NEXT_PUBLIC_API_BASE"] = @"http://127.0.0.1:18765";
    environment[@"PYTHONUNBUFFERED"] = @"1";
    return environment;
}

- (NSFileHandle *)logPipeNamed:(NSString *)name {
    NSURL *target = [self.stateDirectory URLByAppendingPathComponent:name];
    [[NSFileManager defaultManager] createFileAtPath:target.path contents:nil attributes:nil];
    return [NSFileHandle fileHandleForWritingAtPath:target.path] ?: [NSFileHandle fileHandleWithNullDevice];
}

- (void)waitForServices {
    self.readinessAttempts = 0;
    [self.readinessTimer invalidate];
    self.readinessTimer = [NSTimer scheduledTimerWithTimeInterval:0.5
                                                             target:self
                                                           selector:@selector(checkServices:)
                                                           userInfo:nil
                                                            repeats:YES];
}

- (void)checkServices:(NSTimer *)timer {
    self.readinessAttempts += 1;
    if (self.readinessAttempts > 180) {
        [timer invalidate];
        [self showStatus:@"启动超时，请查看 ~/Library/Application Support/CS Board/ 下的日志"];
        return;
    }

    dispatch_group_t group = dispatch_group_create();
    __block BOOL backendReady = NO;
    __block BOOL frontendReady = NO;
    dispatch_group_enter(group);
    [self requestURL:@"http://127.0.0.1:18765/api/health" completion:^(BOOL success) {
        backendReady = success;
        dispatch_group_leave(group);
    }];
    dispatch_group_enter(group);
    [self requestURL:@"http://127.0.0.1:13000" completion:^(BOOL success) {
        frontendReady = success;
        dispatch_group_leave(group);
    }];
    dispatch_group_notify(group, dispatch_get_main_queue(), ^{
        if (backendReady && frontendReady) {
            [timer invalidate];
            [self.webView loadRequest:[NSURLRequest requestWithURL:[NSURL URLWithString:@"http://127.0.0.1:13000"]]];
        } else {
            [self showStatus:[NSString stringWithFormat:@"正在启动服务…（%ld/180）", (long)self.readinessAttempts]];
        }
    });
}

- (void)requestURL:(NSString *)address completion:(void (^)(BOOL success))completion {
    NSURL *url = [NSURL URLWithString:address];
    if (!url) {
        completion(NO);
        return;
    }
    NSURLSessionDataTask *task = [[NSURLSession sharedSession] dataTaskWithURL:url
                                                               completionHandler:^(NSData *data, NSURLResponse *response, NSError *error) {
        BOOL success = [response isKindOfClass:NSHTTPURLResponse.class] &&
                       ((NSHTTPURLResponse *)response).statusCode == 200 &&
                       error == nil;
        dispatch_async(dispatch_get_main_queue(), ^{ completion(success); });
    }];
    [task resume];
}

- (void)showStatus:(NSString *)message {
    NSString *escaped = [self escapeHTML:message];
    NSString *html = [NSString stringWithFormat:
        @"<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><style>html,body{height:100%%;margin:0}body{display:grid;place-items:center;background:#f6f0e5;color:#3d3025;font:16px -apple-system,BlinkMacSystemFont,'PingFang SC',sans-serif}main{text-align:center}h1{font-size:26px;font-weight:600}p{color:#806e5f}</style></head><body><main><h1>白板声画工坊</h1><p>%@</p></main></body></html>",
        escaped];
    [self.webView loadHTMLString:html baseURL:nil];
}

- (NSString *)escapeHTML:(NSString *)value {
    NSString *escaped = [value stringByReplacingOccurrencesOfString:@"&" withString:@"&amp;"];
    escaped = [escaped stringByReplacingOccurrencesOfString:@"<" withString:@"&lt;"];
    escaped = [escaped stringByReplacingOccurrencesOfString:@">" withString:@"&gt;"];
    escaped = [escaped stringByReplacingOccurrencesOfString:@"\"" withString:@"&quot;"];
    return escaped;
}

- (NSError *)missingResourceError:(NSString *)path {
    return [NSError errorWithDomain:@"CSBoardLauncher"
                                code:1
                            userInfo:@{NSLocalizedDescriptionKey: [NSString stringWithFormat:@"缺少资源：%@", path]}];
}

- (void)terminateTask:(NSTask *)task {
    if (task.isRunning) [task terminate];
}

@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        NSApplication *application = [NSApplication sharedApplication];
        CSBoardLauncher *delegate = [[CSBoardLauncher alloc] init];
        application.delegate = delegate;
        [application run];
    }
    return 0;
}
