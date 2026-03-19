// サンプル: コールグラフのテスト用Cファイル

#include <stdio.h>

int add(int a, int b) {
    return a + b;
}

int multiply(int a, int b) {
    int result = 0;
    for (int i = 0; i < b; i++) {
        result = add(result, a);
    }
    return result;
}

void print_result(int value) {
    printf("Result: %d\n", value);
}

int main(void) {
    int x = multiply(3, 4);
    print_result(x);
    return 0;
}
