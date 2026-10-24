cmake_minimum_required(VERSION 3.28)
project(backtest LANGUAGES CXX)

# CUDA 版はまだ作らない。オプションだけ用意しておく(デフォルト OFF)
option(BACKTEST_ENABLE_CUDA "CUDA版エンジンをビルドする" OFF)
if(BACKTEST_ENABLE_CUDA)
  enable_language(CUDA)
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# clangd が build/compile_commands.json を読んで補完・エラー表示に使う
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "ビルドの種類" FORCE)
endif()

# 浮動小数点の結果を Python リファレンス実装と一致させるための設定(docs/mvp.md 6章)
# - -ffp-contract=off:掛け算と足し算を FMA 命令にまとめさせない
# - -ffast-math は使わない(足す順番の入れ替えなどを許してしまうため)
# CUDA 側(nvcc は標準で FMA を使う)の方針は、GPU 版に着手するときに決める
add_compile_options(
  $<$<COMPILE_LANGUAGE:CXX>:-ffp-contract=off>
  $<$<COMPILE_LANGUAGE:CXX>:-Wall>
  $<$<COMPILE_LANGUAGE:CXX>:-Wextra>
)

# GoogleTest(バージョンとハッシュを固定して取得する)
include(FetchContent)
FetchContent_Declare(
  googletest
  URL https://github.com/google/googletest/releases/download/v1.18.0/googletest-1.18.0.tar.gz
  URL_HASH SHA256=6e3191c1455468b3fc35a417fb565c1c5071aee1b7e7f85e30cf48a98d37d8b5
)
set(INSTALL_GTEST OFF CACHE BOOL "" FORCE)
FetchContent_MakeAvailable(googletest)

enable_testing()
include(GoogleTest)

# C++ 版エンジン(開発者が書く。docs/cpp/README.md)。engine/cpp/CMakeLists.txt ができたら自動で組み込む。
# CONFIGURE_DEPENDS:ビルドのたびに「ファイルができたか」を確かめ、できていたら設定をやり直す
# (すでにある build/ でも、cmake を打ち直さずに make test だけで組み込まれる)
file(GLOB BACKTEST_ENGINE_CPP_LISTS CONFIGURE_DEPENDS "${CMAKE_SOURCE_DIR}/engine/cpp/CMakeLists.txt")
if(BACKTEST_ENGINE_CPP_LISTS)
  add_subdirectory(engine/cpp)
endif()

add_subdirectory(tests/cpp)
