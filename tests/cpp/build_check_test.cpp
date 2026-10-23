// ビルド環境の確認用テスト。C++17 でコンパイルされ、GoogleTest が動くことだけを確かめる。
#include <gtest/gtest.h>

#include <optional>

TEST(BuildCheck, CompiledAsCpp17) {
    EXPECT_GE(__cplusplus, 201703L);

    // std::optional は C++17 で追加された機能
    std::optional<int> value = 42;
    ASSERT_TRUE(value.has_value());
    EXPECT_EQ(*value, 42);
}
